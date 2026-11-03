"""Warm worker ownership with immutable per-operation creator inputs."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


def _deep_plain(value):
    if isinstance(value, Mapping):
        return {str(key): _deep_plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_deep_plain(child) for child in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Creator job state contains a non-plain {type(value).__name__} value.")


@dataclass(frozen=True)
class CreatorJob:
    job_id: str
    action: str
    selection_revision: int
    state: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.state, Mapping):
            raise TypeError("Creator job state must be a mapping.")
        object.__setattr__(self, "state", _deep_plain(self.state))


class CreatorInputError(RuntimeError):
    """An input/preparation rejection before the worker was used."""


class CreatorJobRunner:
    """Synchronously execute one admitted creator job on its caller's lane."""

    def __init__(self, *, access, bridge_factory: Callable[[], object], on_stage: Callable) -> None:
        self._access = access
        self._bridge_factory = bridge_factory
        self._on_stage = on_stage
        self._lock = threading.RLock()
        self._startup_lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._cleanup_lock = threading.RLock()
        self._token = ""
        self._job: CreatorJob | None = None
        self._bridge = None
        self._bridge_started = False
        self._captured_process = None
        self._executing = False
        self._closed = False
        self._cleanup_reason = ""
        self._release_waiters = 0
        self._handoff_tickets: set[str] = set()
        self._worker_configuration = None
        self._loading = False
        self._resource_maintenance_active = False
        self._request_started = False

    @property
    def cleanup_pending(self) -> bool:
        with self._lock:
            return bool(self._cleanup_reason)

    def residency_snapshot(self) -> dict:
        exited = self._worker_exited()
        with self._lock:
            releasing = bool(self._release_waiters or self._handoff_tickets or self._closed)
            return {
                "loaded": bool(self._bridge_started and not self._cleanup_reason and not exited),
                "worker_failed": exited,
                "loading": self._loading,
                "busy": self._executing,
                "release_requested": releasing,
                "cleanup_failed": bool(self._cleanup_reason),
                "reason": self._cleanup_reason,
                "pid": getattr(self._captured_process, 'pid', None),
            }

    @contextmanager
    def resource_maintenance(self):
        # Normal cleanup acquires cleanup -> state. Reserve new-job admission
        # briefly; never hold state across backend calls or UI callbacks.
        if not self._cleanup_lock.acquire(blocking=False):
            raise RuntimeError('Avatar Creator is busy.')
        admitted = False
        try:
            with self._idle:
                if (self._executing or self._loading or self._release_waiters
                        or self._handoff_tickets or self._resource_maintenance_active):
                    raise RuntimeError('Avatar Creator is busy.')
                self._resource_maintenance_active = True
                admitted = True
            yield
        finally:
            if admitted:
                with self._idle:
                    self._resource_maintenance_active = False
                    self._idle.notify_all()
            self._cleanup_lock.release()

    def _worker_exited(self) -> bool:
        with self._lock:
            process = self._captured_process if self._bridge_started else None
        return process is not None and process.poll() is not None

    def begin_chat_handoff(self) -> str:
        ticket = uuid.uuid4().hex
        with self._lock:
            self._handoff_tickets.add(ticket)
        try:
            if not self.release("chat startup"):
                raise RuntimeError(self._cleanup_reason or "MuseTalk creator cleanup did not complete.")
        except BaseException:
            self.end_chat_handoff(ticket)
            raise
        return ticket

    def end_chat_handoff(self, ticket: str) -> None:
        with self._lock:
            self._handoff_tickets.discard(str(ticket))

    def _stage(self, job: CreatorJob, stage: str) -> None:
        try:
            self._on_stage(job, stage)
        except Exception:
            pass

    def execute(self, job: CreatorJob, operation: Callable[[], Mapping[str, object]]) -> dict:
        if not isinstance(job, CreatorJob):
            raise TypeError("CreatorJobRunner.execute requires a CreatorJob.")
        if not callable(operation):
            raise TypeError("Creator job operation must be callable.")
        with self._lock:
            if self._closed:
                raise RuntimeError("MuseTalk creator job runner is closed.")
            if (self._executing or self._cleanup_reason or self._release_waiters
                    or self._handoff_tickets or self._resource_maintenance_active):
                raise RuntimeError("Another MuseTalk creator operation is already active.")
            self._executing = True
            self._job = job
            self._request_started = False

        operation_error: BaseException | None = None
        result: dict = {}
        cleanup_ok = False
        try:
            if not self._token:
                self._reserve(job)
            self._stage(job, "running")
            value = operation()
            result = dict(value or {})
        except BaseException as error:
            operation_error = error
        finally:
            # Healthy GPU work retains its worker and reservation. Asset-only work
            # without a worker releases admission immediately.
            with self._cleanup_lock:
                with self._idle:
                    must_cleanup = bool(self._token) and (
                        (operation_error is not None and (
                            not isinstance(operation_error, CreatorInputError) or self._request_started
                        ))
                        or self._closed or not self._bridge_started or self._worker_exited()
                    )
                    if not must_cleanup:
                        self._executing = False
                        self._loading = False
                        self._job = None
                        self._idle.notify_all()
                cleanup_ok = self._cleanup_owned() if must_cleanup else True
                if must_cleanup:
                    with self._idle:
                        self._executing = False
                        self._loading = False
                        self._job = None
                        self._idle.notify_all()

        if operation_error is not None:
            raise operation_error
        if not cleanup_ok:
            raise RuntimeError(self._cleanup_reason or "MuseTalk creator cleanup did not complete.")
        return result

    def _reserve(self, job: CreatorJob) -> None:
        self._stage(job, "reserving")
        if self._access is None:
            raise RuntimeError("Avatar creation access is unavailable.")
        token = self._access.reserve()
        with self._lock:
            self._token = token
        self._access.claim(token)

    def request(self, payload: dict, *, timeout: int) -> dict:
        with self._lock:
            if not self._executing or not self._token:
                raise RuntimeError("MuseTalk bridge requests require an active creator job.")
            if self._closed:
                raise RuntimeError("MuseTalk creator job runner closed before worker startup.")
            self._request_started = True
            bridge = self._bridge
            job = self._job
            needs_start = not self._bridge_started
        configuration = job.state.get("_creator_worker_configuration") if job else None
        if self._bridge_started and (configuration != self._worker_configuration or self._worker_exited()):
            with self._cleanup_lock:
                if not self._cleanup_owned():
                    raise RuntimeError(self._cleanup_reason)
            self._reserve(job)
            needs_start = True
        if needs_start:
            with self._lock:
                self._loading = True
            if job is not None:
                self._stage(job, "starting_worker")
            with self._startup_lock:
                with self._lock:
                    if self._closed:
                        raise RuntimeError("MuseTalk creator job runner closed before worker startup.")
                    bridge = self._bridge
                if bridge is None:
                    bridge = self._bridge_factory()
                    with self._lock:
                        self._bridge = bridge
                try:
                    bridge.start()
                    with self._lock:
                        self._bridge_started = True
                        self._loading = False
                        self._worker_configuration = configuration
                finally:
                    with self._lock:
                        self._captured_process = getattr(bridge, "process", None)
        if job is not None:
            self._stage(job, "requesting")
        return dict(bridge.request(dict(payload), timeout=int(timeout)) or {})

    def _cleanup_owned(self) -> bool:
        with self._lock:
            token = self._token
            bridge = self._bridge
            process = self._captured_process
            job = self._job
        if not token:
            return True
        if job is not None:
            self._stage(job, "stopping_worker")
        reason = ""
        try:
            self._access.begin_cleanup(token)
            if bridge is not None:
                stopper = getattr(bridge, "stop_strict", None) or getattr(bridge, "stop", None)
                if not callable(stopper):
                    raise RuntimeError("MuseTalk bridge has no stop method.")
                stopper()
                if process is not None and process.poll() is None:
                    raise RuntimeError("MuseTalk creator process is still running after stop.")
        except BaseException as error:
            reason = str(error) or type(error).__name__
        cleanup_ok = not reason
        try:
            self._access.finish(token, cleanup_ok=cleanup_ok, reason=reason)
        except BaseException as error:
            cleanup_ok = False
            reason = str(error) or type(error).__name__
        with self._lock:
            self._cleanup_reason = reason
            if cleanup_ok:
                self._token = ""
                self._bridge = None
                self._bridge_started = False
                self._captured_process = None
        if job is not None:
            self._stage(job, "complete" if cleanup_ok else "cleanup_failed")
        return cleanup_ok

    def retry_cleanup(self) -> bool:
        return self.release("cleanup retry")

    def release(self, reason: str = "user") -> bool:
        """Drain on the caller's worker lane, rejecting submissions immediately."""
        with self._idle:
            self._release_waiters += 1
        try:
            with self._idle:
                while self._executing:
                    self._idle.wait()
            with self._cleanup_lock:
                return self._cleanup_owned()
        finally:
            with self._idle:
                self._release_waiters -= 1
                self._idle.notify_all()

    def close(self) -> None:
        with self._startup_lock:
            with self._lock:
                self._closed = True
                executing = self._executing
        if not executing:
            self.retry_cleanup()


__all__ = ["CreatorJob", "CreatorJobRunner"]
