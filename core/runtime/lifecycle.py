"""Runtime lifecycle coordination and owned worker supervision."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
import subprocess
import threading
import time
from typing import Protocol, TypeAlias

from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.identifiers import RunId, WorkLease
from core.runtime.metrics import MonotonicClock


Logger = Callable[[str], None]
LeasePredicate = Callable[[WorkLease], bool]


class ScopeClosedError(RuntimeError):
    """Raised when ownership is offered after matching scope shutdown began."""

    def __init__(self, handle: SupervisedHandle) -> None:
        self.handle = handle
        super().__init__(f"Runtime scope is closing; rejected '{handle.name}'")


class ProcessLike(Protocol):
    """Minimum external-process surface required for bounded shutdown."""

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class Closable(Protocol):
    """An owned resource with deterministic release semantics."""

    def close(self) -> None: ...


class RuntimeService(Protocol):
    """A composed service participating in ordered runtime lifecycle."""

    def start(self) -> CommandResult[None]: ...

    def stop(self) -> CommandResult[None]: ...


class RunGenerationOwner(Protocol):
    @property
    def run_id(self) -> RunId: ...

    def advance_run(self) -> RunId: ...


@dataclass(slots=True, eq=False)
class WorkerHandle:
    """A supervised thread and its non-reused cancellation token."""

    name: str
    thread: threading.Thread
    lease: WorkLease
    token: CancellationToken
    identity: object | None = None
    owner_token: object | None = None
    timed_out: bool = False
    failure: RuntimeFailure | None = None
    _started: bool = field(default=False, repr=False)
    _start_pending: bool = field(default=False, repr=False)
    _start_abandoned: bool = field(default=False, repr=False)
    _start_complete: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
    )
    _on_cancel: Callable[[str], None] | None = field(default=None, repr=False)
    _cancel_callback_claimed: bool = field(default=False, repr=False)

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def _is_active(self) -> bool:
        if self._start_abandoned:
            return False
        if self._start_pending or self.thread.ident is None:
            return True
        self._started = True
        return self.is_alive()


@dataclass(slots=True, eq=False)
class ProcessHandle:
    """A supervised external process with an optional graceful stop hook."""

    name: str
    process: ProcessLike
    lease: WorkLease
    graceful_stop: Callable[[], None] | None = field(default=None, repr=False)
    owner_token: object | None = None
    timed_out: bool = False
    failure: RuntimeFailure | None = None
    terminate_requested: bool = False
    kill_requested: bool = False

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def _is_active(self) -> bool:
        return self.is_alive()


@dataclass(slots=True, eq=False)
class ResourceHandle:
    """A supervised closable resource."""

    name: str
    resource: Closable
    lease: WorkLease
    owner_token: object | None = None
    closed: bool = False
    failure: RuntimeFailure | None = None

    def is_alive(self) -> bool:
        return not self.closed

    def _is_active(self) -> bool:
        return not self.closed


SupervisedHandle: TypeAlias = WorkerHandle | ProcessHandle | ResourceHandle
HandlePredicate = Callable[[SupervisedHandle], bool]


@dataclass(frozen=True, slots=True)
class RuntimeFailureSnapshot:
    """One immutable, ordered runtime cleanup or service failure."""

    sequence: int
    source_kind: str
    source_name: str
    operation: str
    lease: WorkLease | None
    failure: RuntimeFailure
    owner_token: object | None = None


class _ProcessWaitResult(Enum):
    EXITED = auto()
    FAILED = auto()
    TIMED_OUT = auto()


@dataclass(slots=True)
class _PendingShutdown:
    run_id: RunId
    services: tuple[RuntimeService, ...]


@dataclass(frozen=True, slots=True)
class _ClosingScope:
    predicate: HandlePredicate
    reason: str


class WorkerSupervisor:
    """Own threads, processes, and closables by lease and optional owner token."""

    def __init__(
        self,
        join_timeout_seconds: float = 4.0,
        *,
        clock: MonotonicClock = time.monotonic,
        logger: Logger | None = None,
        kill_processes_on_timeout: bool = True,
    ) -> None:
        self._join_timeout_seconds = max(0.0, float(join_timeout_seconds))
        self._clock = clock
        self._logger = logger
        self._kill_processes_on_timeout = bool(kill_processes_on_timeout)
        self._lock = threading.Lock()
        self._handles: list[SupervisedHandle] = []
        self._claimed_handle_ids: set[int] = set()
        self._closing_scopes: list[_ClosingScope] = []
        self._scope_revision = 0
        self._failures: list[RuntimeFailureSnapshot] = []
        self._next_failure_sequence = 1

    def failures(self) -> tuple[RuntimeFailureSnapshot, ...]:
        with self._lock:
            return tuple(self._failures)

    def register(
        self,
        *,
        name: str,
        thread: threading.Thread,
        lease: WorkLease,
        token: CancellationToken,
        identity: object | None = None,
        owner_token: object | None = None,
    ) -> WorkerHandle:
        handle = WorkerHandle(
            name=str(name),
            thread=thread,
            lease=lease,
            token=token,
            identity=identity,
            owner_token=owner_token,
            _started=thread.ident is not None or thread.is_alive(),
        )
        handle._start_complete.set()
        self._register_handle(handle)
        return handle

    def spawn(
        self,
        *,
        name: str,
        lease: WorkLease,
        target: Callable[[CancellationToken], None],
        daemon: bool = True,
        on_cancel: Callable[[str], None] | None = None,
        identity: object | None = None,
        owner_token: object | None = None,
    ) -> WorkerHandle:
        token = CancellationToken()
        handle_holder: list[WorkerHandle] = []

        def run() -> None:
            handle = handle_holder[0]
            try:
                target(token)
            except BaseException as exc:
                failure = RuntimeFailure(
                    "worker_failed",
                    f"Worker '{handle.name}' failed: {exc}",
                    exc,
                )
                self._record_handle_failure(handle, "target", failure)
            finally:
                self._discard(handle)

        thread = threading.Thread(target=run, name=str(name), daemon=daemon)
        handle = WorkerHandle(
            name=str(name),
            thread=thread,
            lease=lease,
            token=token,
            identity=identity,
            owner_token=owner_token,
            _start_pending=True,
            _on_cancel=on_cancel,
        )
        self._register_handle(handle)
        handle_holder.append(handle)
        try:
            thread.start()
        except BaseException as exc:
            self._record_handle_failure(
                handle,
                "start",
                RuntimeFailure(
                    "worker_start_failed",
                    f"Could not start worker '{handle.name}': {exc}",
                    exc,
                ),
            )
            try:
                # enumerate() includes start-pending threads before ident publication.
                potentially_launched = (
                    thread in threading.enumerate()
                    or thread.ident is not None
                    or thread.is_alive()
                )
            except BaseException:
                potentially_launched = True
            with self._lock:
                handle._started = potentially_launched
                handle._start_pending = False
                handle._start_abandoned = not potentially_launched
            handle._start_complete.set()
            if not potentially_launched:
                self._discard(handle)
            raise
        with self._lock:
            handle._started = True
            handle._start_pending = False
        handle._start_complete.set()
        return handle

    def register_process(
        self,
        *,
        name: str,
        process: ProcessLike,
        lease: WorkLease,
        graceful_stop: Callable[[], None] | None = None,
        owner_token: object | None = None,
    ) -> ProcessHandle:
        handle = ProcessHandle(
            name=str(name),
            process=process,
            lease=lease,
            graceful_stop=graceful_stop,
            owner_token=owner_token,
        )
        self._register_handle(handle)
        return handle

    def register_resource(
        self,
        *,
        name: str,
        resource: Closable,
        lease: WorkLease,
        owner_token: object | None = None,
    ) -> ResourceHandle:
        handle = ResourceHandle(
            name=str(name),
            resource=resource,
            lease=lease,
            owner_token=owner_token,
        )
        self._register_handle(handle)
        return handle

    def active_for(self, predicate: LeasePredicate) -> tuple[SupervisedHandle, ...]:
        return self._active_for_handles(lambda handle: predicate(handle.lease))

    def active_for_owner(self, owner_token: object) -> tuple[SupervisedHandle, ...]:
        return self._active_for_handles(
            lambda handle: handle.owner_token == owner_token
        )

    def _active_for_handles(
        self,
        predicate: HandlePredicate,
    ) -> tuple[SupervisedHandle, ...]:
        snapshot = self._snapshot()
        active: list[SupervisedHandle] = []
        terminal: list[SupervisedHandle] = []
        for handle in snapshot:
            if self._handle_is_active(handle):
                if predicate(handle):
                    active.append(handle)
            else:
                terminal.append(handle)
        self._discard_many(terminal)
        return tuple(active)

    def cancel_handles(
        self,
        handles: Sequence[WorkerHandle],
        reason: str,
    ) -> tuple[WorkerHandle, ...]:
        """Cancel only the supplied supervised workers, independent of lease sharing."""

        selected = tuple(dict.fromkeys(handles))
        for handle in selected:
            if self._handle_is_active(handle):
                self._cancel_worker_handle(handle, reason)
        return selected

    def join_handles(
        self,
        handles: Sequence[WorkerHandle],
    ) -> tuple[WorkerHandle, ...]:
        """Join only supplied workers while preserving supervisor claim ownership."""

        requested_ids = {id(handle) for handle in handles}
        snapshot = self._snapshot()
        with self._lock:
            registered_ids = {id(handle) for handle in self._handles}
            selected = tuple(
                handle
                for handle in snapshot
                if isinstance(handle, WorkerHandle)
                and id(handle) in requested_ids
                and id(handle) in registered_ids
                and id(handle) not in self._claimed_handle_ids
            )
            self._claimed_handle_ids.update(id(handle) for handle in selected)
        for handle in selected:
            self._join_worker(handle)
            self._finish_claim(handle)
        return selected

    def cancel_scope(
        self,
        predicate: LeasePredicate,
        reason: str,
    ) -> tuple[WorkerHandle, ...]:
        return self._cancel_handle_scope(
            lambda handle: predicate(handle.lease),
            reason,
        )

    def cancel_owner(
        self,
        owner_token: object,
        reason: str,
    ) -> tuple[WorkerHandle, ...]:
        return self._cancel_handle_scope(
            lambda handle: handle.owner_token == owner_token,
            reason,
        )

    def _cancel_handle_scope(
        self,
        predicate: HandlePredicate,
        reason: str,
    ) -> tuple[WorkerHandle, ...]:
        self._begin_closing_scope(predicate, reason)
        workers = tuple(
            handle
            for handle in self._snapshot()
            if isinstance(handle, WorkerHandle)
            and self._handle_is_active(handle)
            and predicate(handle)
        )
        for handle in workers:
            self._cancel_worker_handle(handle, reason)
        return workers

    def join_scope(self, predicate: LeasePredicate) -> tuple[SupervisedHandle, ...]:
        return self._join_handle_scope(lambda handle: predicate(handle.lease))

    def join_owner(self, owner_token: object) -> tuple[SupervisedHandle, ...]:
        return self._join_handle_scope(
            lambda handle: handle.owner_token == owner_token
        )

    def _join_handle_scope(
        self,
        predicate: HandlePredicate,
    ) -> tuple[SupervisedHandle, ...]:
        selected = self._claim_scope(predicate)
        for handle in selected:
            if isinstance(handle, WorkerHandle):
                self._join_worker(handle)
            elif isinstance(handle, ProcessHandle):
                self._stop_process(handle)
            else:
                self._close_resource(handle)
            self._finish_claim(handle)
        return selected

    def stop_all(self, reason: str) -> tuple[SupervisedHandle, ...]:
        def all_leases(lease: WorkLease) -> bool:
            return True

        self.cancel_scope(all_leases, reason)
        return self.join_scope(all_leases)

    def _snapshot(self) -> tuple[SupervisedHandle, ...]:
        with self._lock:
            return tuple(self._handles)

    def _register_handle(self, handle: SupervisedHandle) -> None:
        closing_reason = self._publish_handle(handle)
        if closing_reason is None:
            return
        if isinstance(handle, WorkerHandle):
            self._cancel_worker_handle(handle, closing_reason)
            if handle._start_pending and handle.thread.ident is None:
                with self._lock:
                    handle._start_pending = False
                    handle._start_abandoned = True
                handle._start_complete.set()
            else:
                self._join_worker(handle)
        elif isinstance(handle, ProcessHandle):
            self._stop_process(handle)
        else:
            self._close_resource(handle)
        self._finish_claim(handle)
        raise ScopeClosedError(handle)

    def _cancel_worker_handle(self, handle: WorkerHandle, reason: str) -> None:
        handle.token.cancel(reason)
        callback = None
        with self._lock:
            if (
                handle._on_cancel is not None
                and not handle._cancel_callback_claimed
            ):
                handle._cancel_callback_claimed = True
                callback = handle._on_cancel
        if callback is None:
            return
        try:
            callback(str(reason))
        except BaseException as exc:
            self._record_handle_failure(
                handle,
                "cancel_callback",
                RuntimeFailure(
                    "worker_cancel_callback_failed",
                    f"Cancellation callback for worker '{handle.name}' failed: {exc}",
                    exc,
                ),
            )

    def _publish_handle(self, handle: SupervisedHandle) -> str | None:
        while True:
            with self._lock:
                closing_scopes = tuple(self._closing_scopes)
                revision = self._scope_revision
            matching_reason = next(
                (
                    scope.reason
                    for scope in closing_scopes
                    if scope.predicate(handle)
                ),
                None,
            )
            with self._lock:
                if revision != self._scope_revision:
                    continue
                self._handles.append(handle)
                if matching_reason is not None:
                    self._claimed_handle_ids.add(id(handle))
                return matching_reason

    def _begin_closing_scope(self, predicate: HandlePredicate, reason: str) -> None:
        with self._lock:
            self._closing_scopes.append(_ClosingScope(predicate, str(reason)))
            self._scope_revision += 1

    def _claim_scope(
        self,
        predicate: HandlePredicate,
    ) -> tuple[SupervisedHandle, ...]:
        self._begin_closing_scope(predicate, "scope_shutdown")
        snapshot = self._snapshot()
        matching_ids = {
            id(handle) for handle in snapshot if predicate(handle)
        }
        with self._lock:
            registered_ids = {id(handle) for handle in self._handles}
            claimed = tuple(
                handle
                for handle in snapshot
                if id(handle) in matching_ids
                and id(handle) in registered_ids
                and id(handle) not in self._claimed_handle_ids
            )
            self._claimed_handle_ids.update(id(handle) for handle in claimed)
        return claimed

    def _finish_claim(self, handle: SupervisedHandle) -> None:
        active = self._handle_is_active(handle)
        with self._lock:
            self._claimed_handle_ids.discard(id(handle))
            if not active:
                try:
                    self._handles.remove(handle)
                except ValueError:
                    pass

    def _discard(self, handle: SupervisedHandle) -> None:
        with self._lock:
            if id(handle) in self._claimed_handle_ids:
                return
            try:
                self._handles.remove(handle)
            except ValueError:
                pass

    def _discard_many(self, handles) -> None:
        terminal_ids = {id(handle) for handle in handles}
        if not terminal_ids:
            return
        with self._lock:
            self._handles[:] = [
                handle
                for handle in self._handles
                if id(handle) not in terminal_ids
                or id(handle) in self._claimed_handle_ids
            ]

    def _handle_is_active(self, handle: SupervisedHandle) -> bool:
        try:
            return handle._is_active()
        except BaseException as exc:
            failure = RuntimeFailure(
                "worker_status_failed",
                f"Could not inspect supervised handle '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, "status", failure)
            return True

    def _join_worker(self, handle: WorkerHandle) -> None:
        if handle._start_pending:
            handle._start_complete.wait(self._join_timeout_seconds)
            if handle._start_pending:
                handle.timed_out = True
                self._record_handle_failure(
                    handle,
                    "start_wait",
                    RuntimeFailure(
                        "worker_start_timeout",
                        f"Worker '{handle.name}' start timed out after "
                        f"{self._join_timeout_seconds:.3f}s",
                    ),
                )
                return
        if not handle.is_alive():
            return
        deadline = self._clock() + self._join_timeout_seconds
        try:
            handle.thread.join(max(0.0, deadline - self._clock()))
        except BaseException as exc:
            failure = RuntimeFailure(
                "worker_join_failed",
                f"Could not join worker '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, "join", failure)
            return
        if handle.is_alive():
            handle.timed_out = True
            self._record_handle_failure(
                handle,
                "join",
                RuntimeFailure(
                    "worker_join_timeout",
                    f"Worker '{handle.name}' timed out after "
                    f"{self._join_timeout_seconds:.3f}s",
                ),
            )

    def _stop_process(self, handle: ProcessHandle) -> None:
        if handle.graceful_stop is not None:
            try:
                handle.graceful_stop()
            except BaseException as exc:
                failure = RuntimeFailure(
                    "process_graceful_stop_failed",
                    f"Graceful stop for process '{handle.name}' failed: {exc}",
                    exc,
                )
                self._record_handle_failure(handle, "graceful_stop", failure)
        if not self._handle_is_active(handle):
            return
        try:
            handle.terminate_requested = True
            handle.process.terminate()
        except BaseException as exc:
            failure = RuntimeFailure(
                "process_terminate_failed",
                f"Could not terminate process '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, "terminate", failure)

        wait_result = self._wait_for_process(
            handle,
            self._join_timeout_seconds,
            operation="wait_after_terminate",
            timeout_category="process_wait_timeout",
        )
        if wait_result is _ProcessWaitResult.EXITED:
            return
        if wait_result is _ProcessWaitResult.FAILED:
            return
        if wait_result is _ProcessWaitResult.TIMED_OUT:
            handle.timed_out = True
        if not self._kill_processes_on_timeout:
            return
        try:
            handle.kill_requested = True
            handle.process.kill()
        except BaseException as exc:
            failure = RuntimeFailure(
                "process_kill_failed",
                f"Could not kill process '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, "kill", failure)
        self._wait_for_process(
            handle,
            self._join_timeout_seconds,
            operation="wait_after_kill",
            timeout_category="process_kill_wait_timeout",
        )

    def _wait_for_process(
        self,
        handle: ProcessHandle,
        timeout: float,
        *,
        operation: str,
        timeout_category: str,
    ) -> _ProcessWaitResult:
        deadline = self._clock() + timeout
        try:
            handle.process.wait(max(0.0, deadline - self._clock()))
            return _ProcessWaitResult.EXITED
        except subprocess.TimeoutExpired:
            self._record_handle_failure(
                handle,
                operation,
                RuntimeFailure(
                    timeout_category,
                    f"Process '{handle.name}' timed out after wait of "
                    f"{timeout:.3f}s",
                ),
            )
            return _ProcessWaitResult.TIMED_OUT
        except BaseException as exc:
            failure = RuntimeFailure(
                "process_wait_failed",
                f"Could not wait for process '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, operation, failure)
            return _ProcessWaitResult.FAILED

    def _close_resource(self, handle: ResourceHandle) -> None:
        try:
            handle.resource.close()
        except BaseException as exc:
            failure = RuntimeFailure(
                "resource_close_failed",
                f"Could not close resource '{handle.name}': {exc}",
                exc,
            )
            self._record_handle_failure(handle, "close", failure)
            return
        handle.closed = True

    def _record_handle_failure(
        self,
        handle: SupervisedHandle,
        operation: str,
        failure: RuntimeFailure,
    ) -> RuntimeFailureSnapshot:
        if handle.failure is None:
            handle.failure = failure
        return self._record_failure(
            source_kind=(
                "worker"
                if isinstance(handle, WorkerHandle)
                else "process"
                if isinstance(handle, ProcessHandle)
                else "resource"
            ),
            source_name=handle.name,
            operation=operation,
            lease=handle.lease,
            failure=failure,
            owner_token=handle.owner_token,
        )

    def _record_failure(
        self,
        *,
        source_kind: str,
        source_name: str,
        operation: str,
        lease: WorkLease | None,
        failure: RuntimeFailure,
        owner_token: object | None = None,
        additional_logger: Logger | None = None,
    ) -> RuntimeFailureSnapshot:
        with self._lock:
            snapshot = RuntimeFailureSnapshot(
                sequence=self._next_failure_sequence,
                source_kind=source_kind,
                source_name=source_name,
                operation=operation,
                lease=lease,
                failure=failure,
                owner_token=owner_token,
            )
            self._next_failure_sequence += 1
            self._failures.append(snapshot)
        self._log(failure.message)
        if additional_logger is not None and additional_logger is not self._logger:
            self._call_logger(additional_logger, failure.message)
        return snapshot

    def _log(self, message: str) -> None:
        self._call_logger(self._logger, message)

    @staticmethod
    def _call_logger(logger: Logger | None, message: str) -> None:
        if logger is None:
            return
        try:
            logger(message)
        except BaseException:
            pass


class RuntimeLifecycle:
    """Start and stop composed services while invalidating stale run leases."""

    def __init__(
        self,
        services: Sequence[RuntimeService],
        *,
        supervisor: WorkerSupervisor | None = None,
        logger: Logger | None = None,
        run_generation: RunGenerationOwner | None = None,
    ) -> None:
        self._services = tuple(services)
        self._supervisor = supervisor or WorkerSupervisor(logger=logger)
        self._logger = logger
        self._lock = threading.Lock()
        self._run_generation = run_generation
        self._run_id = run_generation.run_id if run_generation is not None else RunId(1)
        self._running = False
        self._transitioning = False
        self._started_services: tuple[RuntimeService, ...] = ()
        self._pending_shutdowns: list[_PendingShutdown] = []

    @property
    def supervisor(self) -> WorkerSupervisor:
        return self._supervisor

    @property
    def run_id(self) -> RunId:
        owner = self._run_generation
        if owner is not None:
            return owner.run_id
        with self._lock:
            return self._run_id

    def failures(self) -> tuple[RuntimeFailureSnapshot, ...]:
        return self._supervisor.failures()

    def start(self) -> CommandResult[None]:
        with self._lock:
            if self._transitioning:
                return self._busy_result()
            if self._running:
                return CommandResult(True)
            retry_pending_cleanup = bool(self._pending_shutdowns)
            self._transitioning = True

        if retry_pending_cleanup:
            cleanup_failure = self._cleanup_pending_shutdowns(
                "runtime_start_cleanup_retry"
            )
            if cleanup_failure is not None:
                with self._lock:
                    self._transitioning = False
                return CommandResult(False, failure=cleanup_failure)

        with self._lock:
            starting_run_id = self._run_id
        result, started = self._start_services(starting_run_id)
        if not result.accepted:
            self._rollback_failed_start(starting_run_id, started)
        with self._lock:
            self._transitioning = False
            self._running = result.accepted
            self._started_services = started if result.accepted else ()
        return result

    def restart(self, reason: str) -> CommandResult[RunId]:
        with self._lock:
            if self._transitioning:
                busy = self._busy_result()
                return CommandResult(False, failure=busy.failure)
            old_run_id = self._run_id
            was_running = self._running
            had_pending = bool(self._pending_shutdowns)
            if was_running:
                self._pending_shutdowns.append(
                    _PendingShutdown(old_run_id, self._started_services)
                )
            self._running = False
            self._started_services = ()
            self._transitioning = True

        if was_running:
            self._advance_run()
        stop_failure = self._cleanup_pending_shutdowns(reason)
        if stop_failure is None:
            if not was_running and not had_pending:
                self._advance_run()
            new_run_id = self.run_id
            start_result, newly_started = self._start_services(new_run_id)
            if not start_result.accepted:
                self._rollback_failed_start(new_run_id, newly_started)
        else:
            start_result = CommandResult(False, failure=stop_failure)
            newly_started = ()

        with self._lock:
            self._transitioning = False
            self._running = start_result.accepted
            self._started_services = newly_started if start_result.accepted else ()
        if not start_result.accepted:
            return CommandResult(False, failure=start_result.failure)
        return CommandResult(True, value=new_run_id)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            if self._transitioning:
                return self._busy_result()
            if not self._running and not self._pending_shutdowns:
                return CommandResult(True)
            if self._running:
                old_run_id = self._run_id
                self._pending_shutdowns.append(
                    _PendingShutdown(old_run_id, self._started_services)
                )
            run_to_advance = next(
                (
                    pending.run_id
                    for pending in self._pending_shutdowns
                    if pending.run_id == self._run_id
                ),
                None,
            )
            self._running = False
            self._started_services = ()
            self._transitioning = True

        barrier_failure = self._cancel_generation_barriers(
            tuple(
                pending
                for pending in self._pending_shutdowns
                if pending.run_id == run_to_advance
            ),
            "runtime_shutdown",
        )
        if barrier_failure is None:
            if run_to_advance is not None:
                self._advance_run()
            failure = self._cleanup_pending_shutdowns("runtime_shutdown")
        else:
            failure = barrier_failure

        with self._lock:
            self._transitioning = False
        if failure is not None:
            return CommandResult(False, failure=failure)
        return CommandResult(True)

    def _cancel_generation_barriers(
        self,
        pending_shutdowns: Sequence[_PendingShutdown],
        reason: str,
    ) -> RuntimeFailure | None:
        for pending in pending_shutdowns:
            for service in reversed(pending.services):
                cancel_all = getattr(service, "cancel_all", None)
                if (
                    getattr(service, "name", "") != "replay"
                    or not callable(cancel_all)
                ):
                    continue
                try:
                    result = cancel_all(reason)
                except BaseException as exc:
                    failure = RuntimeFailure(
                        "service_cancel_all_failed",
                        f"{type(service).__name__}.cancel_all() failed: {exc}",
                        exc,
                    )
                    self._record_service_failure(
                        service,
                        "cancel_all",
                        pending.run_id,
                        failure,
                    )
                    return failure
                if not isinstance(result, CommandResult) or not result.accepted:
                    failure = (
                        result.failure
                        if isinstance(result, CommandResult) and result.failure is not None
                        else RuntimeFailure(
                            "service_cancel_all_failed",
                            f"{type(service).__name__}.cancel_all() rejected shutdown",
                        )
                    )
                    self._record_service_failure(
                        service,
                        "cancel_all",
                        pending.run_id,
                        failure,
                    )
                    return failure
        return None

    def _advance_run(self) -> RunId:
        owner = self._run_generation
        if owner is None:
            with self._lock:
                self._run_id = RunId(self._run_id.value + 1)
                return self._run_id
        else:
            run_id = owner.advance_run()
            with self._lock:
                self._run_id = run_id
            return run_id

    def _cleanup_pending_shutdowns(self, reason: str) -> RuntimeFailure | None:
        with self._lock:
            pending_shutdowns = tuple(self._pending_shutdowns)

        first_failure: RuntimeFailure | None = None
        remaining_shutdowns: list[_PendingShutdown] = []
        for pending in pending_shutdowns:
            def pending_scope(lease: WorkLease, run_id: RunId = pending.run_id) -> bool:
                return lease.run_id == run_id

            failure_count = len(self._supervisor.failures())
            self._supervisor.cancel_scope(pending_scope, reason)
            service_failure, remaining_services = self._stop_services(
                pending.services,
                pending.run_id,
            )
            self._supervisor.join_scope(pending_scope)
            remaining_handles = self._supervisor.active_for(pending_scope)
            incomplete = self._incomplete_shutdown_failure(remaining_handles)
            attempt_failures = self._supervisor.failures()[failure_count:]
            failure = service_failure or incomplete
            if failure is None and attempt_failures:
                failure = attempt_failures[0].failure
            if failure is not None:
                remaining_shutdowns.append(
                    _PendingShutdown(pending.run_id, remaining_services)
                )
                if first_failure is None:
                    first_failure = failure

        with self._lock:
            self._pending_shutdowns = remaining_shutdowns
        return first_failure

    def _start_services(
        self,
        run_id: RunId,
    ) -> tuple[CommandResult[None], tuple[RuntimeService, ...]]:
        started: list[RuntimeService] = []
        for service in self._services:
            result = self._call_service(service, "start", run_id)
            if not result.accepted:
                return result, tuple(started)
            started.append(service)
        return CommandResult(True), tuple(started)

    def _rollback_failed_start(
        self,
        failed_run_id: RunId,
        started_services: Sequence[RuntimeService],
    ) -> None:
        with self._lock:
            should_advance = self._run_id == failed_run_id
        if should_advance:
            self._advance_run()

        def failed_scope(lease: WorkLease) -> bool:
            return lease.run_id == failed_run_id

        failure_count = len(self._supervisor.failures())
        self._supervisor.cancel_scope(failed_scope, "runtime_start_failed")
        rollback_failure, remaining_services = self._stop_services(
            started_services,
            failed_run_id,
        )
        self._supervisor.join_scope(failed_scope)
        remaining_handles = self._supervisor.active_for(failed_scope)
        rollback_failures = self._supervisor.failures()[failure_count:]
        incomplete = self._incomplete_shutdown_failure(remaining_handles)
        if rollback_failure is not None or incomplete is not None or rollback_failures:
            with self._lock:
                self._pending_shutdowns.append(
                    _PendingShutdown(failed_run_id, remaining_services)
                )

    def _stop_services(
        self,
        services: Sequence[RuntimeService],
        run_id: RunId,
    ) -> tuple[RuntimeFailure | None, tuple[RuntimeService, ...]]:
        first_failure: RuntimeFailure | None = None
        failed_services: list[RuntimeService] = []
        for service in reversed(services):
            result = self._call_service(service, "stop", run_id)
            if not result.accepted:
                failed_services.append(service)
                if first_failure is None:
                    first_failure = result.failure or RuntimeFailure(
                        "service_stop_failed",
                        f"{type(service).__name__}.stop() rejected shutdown",
                    )
        failed_service_ids = {id(service) for service in failed_services}
        return first_failure, tuple(
            service for service in services if id(service) in failed_service_ids
        )

    def _call_service(
        self,
        service: RuntimeService,
        operation: str,
        run_id: RunId,
    ) -> CommandResult[None]:
        try:
            result = getattr(service, operation)()
        except BaseException as exc:
            failure = RuntimeFailure(
                f"service_{operation}_failed",
                f"{type(service).__name__}.{operation}() failed: {exc}",
                exc,
            )
            self._record_service_failure(service, operation, run_id, failure)
            return CommandResult(False, failure=failure)
        if isinstance(result, CommandResult):
            if result.accepted:
                return result
            failure = result.failure or RuntimeFailure(
                f"service_{operation}_failed",
                f"{type(service).__name__}.{operation}() rejected the transition",
            )
            self._record_service_failure(service, operation, run_id, failure)
            return CommandResult(False, value=result.value, failure=failure)
        failure = RuntimeFailure(
            f"service_{operation}_failed",
            f"{type(service).__name__}.{operation}() returned an invalid result",
        )
        self._record_service_failure(service, operation, run_id, failure)
        return CommandResult(False, failure=failure)

    def _record_service_failure(
        self,
        service: RuntimeService,
        operation: str,
        run_id: RunId,
        failure: RuntimeFailure,
    ) -> None:
        self._supervisor._record_failure(
            source_kind="service",
            source_name=str(getattr(service, "name", type(service).__name__)),
            operation=operation,
            lease=WorkLease(run_id),
            failure=failure,
            additional_logger=self._logger,
        )

    @staticmethod
    def _incomplete_shutdown_failure(
        handles: Sequence[SupervisedHandle],
    ) -> RuntimeFailure | None:
        if not handles:
            return None
        return RuntimeFailure(
            "runtime_shutdown_incomplete",
            "Supervised handles did not stop: "
            + ", ".join(handle.name for handle in handles),
        )

    @staticmethod
    def _busy_result() -> CommandResult[None]:
        return CommandResult(
            False,
            failure=RuntimeFailure(
                "lifecycle_busy",
                "A runtime lifecycle transition is already in progress",
            ),
        )

    def _log(self, message: str) -> None:
        if self._logger is None:
            return
        try:
            self._logger(message)
        except BaseException:
            pass


__all__ = [
    "Closable",
    "ProcessHandle",
    "ProcessLike",
    "ResourceHandle",
    "RuntimeFailureSnapshot",
    "RuntimeLifecycle",
    "RuntimeService",
    "ScopeClosedError",
    "SupervisedHandle",
    "WorkerHandle",
    "WorkerSupervisor",
]
