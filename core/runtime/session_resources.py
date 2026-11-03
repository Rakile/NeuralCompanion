"""Lease checks for effects derived from one conversation session."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease


T = TypeVar("T")


class SessionLeaseOwner(Protocol):
    def session_lease_is_current(self, lease: WorkLease) -> bool: ...

    def admit_session_effect(self, lease: WorkLease) -> object | None: ...

    def release_session_effect(self, admission: object) -> None: ...


class SessionResourceGuard:
    """Admit current work and drain it before the owning session can advance."""

    def __init__(self, owner: SessionLeaseOwner) -> None:
        self._owner = owner

    def commit_database_write(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def commit_memory_write(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def commit_embedding_write(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def link_visual_result(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def publish_image_review(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def commit_state_write(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        return self._execute(lease, effect)

    def _execute(
        self,
        lease: WorkLease,
        effect: Callable[[], T],
    ) -> CommandResult[T]:
        admission = self._owner.admit_session_effect(lease)
        if admission is None:
            return _stale_session_result()
        try:
            value = effect()
        finally:
            self._owner.release_session_effect(admission)
        return CommandResult(accepted=True, value=value)


def _stale_session_result():
    return CommandResult(
        accepted=False,
        failure=RuntimeFailure(
            "stale_session",
            "Session-derived work no longer owns the current session.",
        ),
    )


__all__ = ["SessionResourceGuard"]
