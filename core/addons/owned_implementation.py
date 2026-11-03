"""Addon-local ownership for implementation objects.

The native QML runtime must not obtain addon behavior from a host-owned UI
lifecycle catalog.  This small adapter keeps the existing exact-owner guard
while allowing each addon entry point to own and retire its own implementation.
It intentionally has no Qt or presentation dependency.
"""

from __future__ import annotations

import importlib
import threading
from typing import Any


class OwnedAddonImplementation:
    """Lazily construct one addon implementation for one owner generation."""

    def __init__(self, owner: object, module_name: str, class_name: str = "Addon") -> None:
        self._owner = owner
        self._module_name = str(module_name or "").strip()
        self._class_name = str(class_name or "Addon").strip() or "Addon"
        if not self._module_name:
            raise ValueError("An addon implementation module is required.")
        self._lock = threading.RLock()
        self._implementation: Any | None = None

    def _authorize(self, owner: object) -> None:
        if owner != self._owner:
            raise PermissionError("Addon implementation rejected a different owner generation.")

    def initialize(self, owner: object, projection: object) -> None:
        self._authorize(owner)
        with self._lock:
            if self._implementation is not None:
                raise RuntimeError("Addon implementation is already initialized.")
            module = importlib.import_module(self._module_name)
            implementation_type = getattr(module, self._class_name)
            implementation = implementation_type()
            implementation.initialize(projection)
            self._implementation = implementation

    def _target(self, name: str) -> Any:
        with self._lock:
            implementation = self._implementation
        if implementation is None:
            raise RuntimeError("Addon implementation is not initialized.")
        operation = getattr(implementation, name, None)
        if callable(operation):
            return operation
        controller = getattr(implementation, "controller", None)
        operation = getattr(controller, name, None)
        if callable(operation):
            return operation
        raise AttributeError(
            f"Addon implementation '{self._module_name}' has no operation '{name}'."
        )

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def invoke(owner: object, *args, **kwargs):
            self._authorize(owner)
            return self._target(name)(*args, **kwargs)

        return invoke

    def shutdown(self, owner: object) -> None:
        self._authorize(owner)
        with self._lock:
            implementation = self._implementation
            self._implementation = None
        if implementation is None:
            return
        shutdown = getattr(implementation, "shutdown", None)
        if callable(shutdown):
            shutdown()


__all__ = ["OwnedAddonImplementation"]
