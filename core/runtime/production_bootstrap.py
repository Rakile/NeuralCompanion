"""Single-owner bootstrap boundary for the production runtime graph."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from core.runtime.context import RuntimeContext
from core.runtime.contracts import CommandResult
from core.runtime.production_host import ProductionApplicationHost

ProductionHostFactory = Callable[[], ProductionApplicationHost]


class ProductionBootstrap:
    """Create exactly one production host and expose only application entry points."""

    __slots__ = ("_factory", "_host", "_lock")

    def __init__(self, factory: ProductionHostFactory) -> None:
        if not callable(factory):
            raise TypeError("Production bootstrap requires a host factory.")
        self._factory = factory
        self._host: ProductionApplicationHost | None = None
        self._lock = threading.Lock()

    def host(self) -> ProductionApplicationHost:
        current = self._host
        if current is not None:
            return current
        with self._lock:
            current = self._host
            if current is None:
                current = self._factory()
                if not isinstance(current, ProductionApplicationHost):
                    raise TypeError(
                        "Production host factory must return ProductionApplicationHost."
                    )
                self._host = current
            return current

    def context(self) -> RuntimeContext:
        return self.host().context

    def run(
        self,
        config_override: Mapping[str, object] | None = None,
    ) -> CommandResult[None]:
        return self.host().run(config_override)

    def request_shutdown(self, reason: str = "user") -> None:
        self.host().request_shutdown(reason)


__all__ = ["ProductionBootstrap", "ProductionHostFactory"]
