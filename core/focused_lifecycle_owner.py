"""Pure ownership contract for host-managed focused addon lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class FocusedLifecycleOwnershipError(PermissionError):
    """Raised when a focused lifecycle handle rejects an owner generation."""


@dataclass(frozen=True, slots=True)
class AddonOwnerToken:
    addon_id: str
    generation: int
    token: UUID


class FocusedLifecycleOwnerBinding(Protocol):
    """Minimal owner state required by a focused lifecycle handle."""

    owner: AddonOwnerToken

    def ensure_open(self) -> None: ...

    @property
    def closed(self) -> bool: ...
