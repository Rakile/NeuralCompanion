"""Dependency-free records shared by runtime services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import logging
from collections.abc import Callable
from typing import Generic, TypeVar


T = TypeVar("T")


class CancellationToken:
    """A thread-safe cancellation signal that records its first cancellation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled_event = threading.Event()
        self._cancelled = False
        self._reason = ""
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback = 0

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "") -> None:
        """Cancel once; later calls cannot repurpose the token."""

        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._reason = str(reason)
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        self._cancelled_event.set()
        for callback in callbacks:
            self._notify(callback)

    @staticmethod
    def _notify(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logging.getLogger(__name__).exception("Cancellation subscriber failed")

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Notify once outside the lock; late subscribers are notified immediately.

        Unsubscribing prevents a pending callback. A callback already admitted by
        cancellation may still run and should tolerate an already-retired owner.
        """
        if not callable(callback):
            raise TypeError("Cancellation subscriber must be callable")
        with self._lock:
            key = self._next_callback
            self._next_callback += 1
            cancelled = self._cancelled
            if not cancelled:
                self._callbacks[key] = callback
        if cancelled:
            self._notify(callback)
        def unsubscribe():
            with self._lock:
                self._callbacks.pop(key, None)
        return unsubscribe

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until cancellation without polling."""

        return self._cancelled_event.wait(timeout)

    @contextmanager
    def admission_scope(self) -> Iterator[bool]:
        """Serialize one short irreversible admission against cancellation."""

        self._lock.acquire()
        if self._cancelled:
            self._lock.release()
            yield False
            return
        try:
            yield True
        finally:
            self._lock.release()

    def is_set(self) -> bool:
        """Event-compatible read for temporary legacy cancellation adapters."""

        return self.cancelled

    def set(self) -> None:
        """Event-compatible cancellation for temporary legacy adapters."""

        self.cancel()


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    """A stable failure description that does not expose its exception by default."""

    category: str
    message: str
    cause: BaseException | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class CommandResult(Generic[T]):
    """The acceptance result for a runtime command."""

    accepted: bool
    value: T | None = None
    failure: RuntimeFailure | None = None


@dataclass(frozen=True, slots=True)
class IdentityRelayTurnState:
    """Frozen Identity Relay identity and authorization references for one turn."""

    enabled: bool
    artifact_ref: str | None
    connection_revision: int
    subject_kind: str | None
    artifact_revision: str | None
    owner_override: bool
    provider_id: str
    model_id: str
    run_generation: int = 0
    session_generation: int = 0
    turn_id: str = ""
    route_generation: int = 0


__all__ = [
    "CancellationToken",
    "CommandResult",
    "IdentityRelayTurnState",
    "RuntimeFailure",
]
