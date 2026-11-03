from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Protocol

from core.runtime.contracts import CommandResult, RuntimeFailure


class BoundRunOwner(Protocol):
    def run(
        self,
        config_override: Mapping[str, object] | None = None,
        *,
        reservation: str | None = None,
    ) -> CommandResult[None]: ...

    def retry_cleanup(self) -> CommandResult[None]: ...


class BoundStopOwner(Protocol):
    def request_stop(self, *, engine_running: bool) -> None: ...


class ProductionRunBinding:
    """Bind the one production run owner after graph construction."""

    __slots__ = ("_lock", "_owner")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: BoundRunOwner | None = None

    def bind(self, owner: BoundRunOwner) -> None:
        if not callable(getattr(owner, "run", None)):
            raise TypeError("Production run binding requires a run owner.")
        with self._lock:
            if self._owner is not None and self._owner is not owner:
                raise RuntimeError("Production run owner is already bound.")
            self._owner = owner

    def __call__(
        self,
        config_override: Mapping[str, object],
        *,
        reservation: str | None = None,
    ) -> CommandResult[None]:
        with self._lock:
            owner = self._owner
        if owner is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "production_run_unbound",
                    "The production runtime has not finished composition.",
                ),
            )
        if reservation is None:
            return owner.run(dict(config_override))
        return owner.run(dict(config_override), reservation=reservation)

    def retry_cleanup(self) -> CommandResult[None]:
        with self._lock:
            owner = self._owner
        if owner is None:
            return CommandResult(True)
        return owner.retry_cleanup()


class ProductionStopBinding:
    """Bind the one production stop owner after graph construction."""

    __slots__ = ("_lock", "_owner")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: BoundStopOwner | None = None

    def bind(self, owner: BoundStopOwner) -> None:
        if not callable(getattr(owner, "request_stop", None)):
            raise TypeError("Production stop binding requires a stop owner.")
        with self._lock:
            if self._owner is not None and self._owner is not owner:
                raise RuntimeError("Production stop owner is already bound.")
            self._owner = owner

    def __call__(self, engine_running: bool) -> None:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError("The production runtime has not finished composition.")
        owner.request_stop(engine_running=bool(engine_running))


__all__ = [
    "BoundRunOwner",
    "BoundStopOwner",
    "ProductionRunBinding",
    "ProductionStopBinding",
]
