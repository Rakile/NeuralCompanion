"""Explicit ownership boundary for the composed production application."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from core.runtime.context import RuntimeContext
from core.runtime.contracts import CommandResult
from core.runtime.facade import ApplicationFacade


class ProductionRunOrchestrator(Protocol):
    def run(
        self,
        config_override: Mapping[str, object] | None = None,
    ) -> CommandResult[None]: ...


class ProductionStopOwner(Protocol):
    def request_stop(self, reason: str = "user") -> None: ...


class ProductionApplicationHost:
    """Own one runtime graph and its finite production entry points.

    The host deliberately exposes no lookup API.  Composition receives the
    concrete owners once; consumers receive only the stable facade or the
    established restricted addon-operation contract.
    """

    __slots__ = (
        "_addon_runtime_operations",
        "_context",
        "_orchestrator",
        "_stop_owner",
    )

    def __init__(
        self,
        *,
        context: RuntimeContext,
        orchestrator: ProductionRunOrchestrator,
        stop_owner: ProductionStopOwner,
        addon_runtime_operations: object,
    ) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("Production host requires RuntimeContext.")
        if not callable(getattr(orchestrator, "run", None)):
            raise TypeError("Production host requires a run orchestrator.")
        if not callable(getattr(stop_owner, "request_stop", None)):
            raise TypeError("Production host requires a stop owner.")
        self._context = context
        self._orchestrator = orchestrator
        self._stop_owner = stop_owner
        self._addon_runtime_operations = addon_runtime_operations

    @property
    def context(self) -> RuntimeContext:
        return self._context

    @property
    def facade(self) -> ApplicationFacade:
        return self._context.facade

    @property
    def addon_runtime_operations(self) -> object:
        return self._addon_runtime_operations

    def run(
        self,
        config_override: Mapping[str, object] | None = None,
    ) -> CommandResult[None]:
        return self._orchestrator.run(dict(config_override or {}))

    def request_shutdown(self, reason: str = "user") -> None:
        self._stop_owner.request_stop(str(reason or "user"))


__all__ = [
    "ProductionApplicationHost",
    "ProductionRunOrchestrator",
    "ProductionStopOwner",
]
