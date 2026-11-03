"""Typed application boundary for the production conversation loop."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.stop_diagnostics import record_runtime_event

if TYPE_CHECKING:
    from core.conversation_flow_v2 import ProductionRunOptions


class ProductionLoopControl(Protocol):
    def prepare_run(self) -> None: ...
    def request_stop(self) -> None: ...


class ProductionServiceGraph(Protocol):
    @property
    def control(self) -> ProductionLoopControl: ...

    def missing_domains(self) -> tuple[str, ...]: ...


class ProductionConversationController(Protocol):
    def run_production(
        self,
        source: object,
        *,
        services: ProductionServiceGraph,
        options: ProductionRunOptions | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProductionApplicationComposition:
    """The finite object graph needed to launch the production loop."""

    controller: ProductionConversationController | None
    source: object | None
    services: ProductionServiceGraph | None
    options: ProductionRunOptions | None = None
    prepare_control_before_run: bool = True

    def missing_domains(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.controller is None:
            missing.append("controller")
        if self.source is None:
            missing.append("source")
        if self.services is None:
            missing.append("services")
        else:
            missing.extend(
                f"services.{name}" for name in self.services.missing_domains()
            )
        return tuple(missing)


class IncompleteProductionCompositionError(ValueError):
    def __init__(self, missing_domains: tuple[str, ...]) -> None:
        self.missing_domains = missing_domains
        joined = ", ".join(missing_domains)
        super().__init__(f"Production application composition is incomplete: {joined}")


class ProductionApplicationRunner:
    """Own the production loop thread and its bounded cancellation lifecycle."""

    def __init__(
        self,
        composition: ProductionApplicationComposition,
        *,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        missing = composition.missing_domains()
        if missing:
            raise IncompleteProductionCompositionError(missing)
        self._composition = composition
        self._controller = cast(
            ProductionConversationController, composition.controller
        )
        self._source = composition.source
        self._services = cast(ProductionServiceGraph, composition.services)
        self._stop_timeout_seconds = max(0.0, float(stop_timeout_seconds))
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._sync_active = False
        self._failure: BaseException | None = None
        self._finished = threading.Event()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._sync_active or (
                self._thread is not None and self._thread.is_alive()
            )

    def run_sync(self) -> CommandResult[None]:
        """Run in the caller-owned thread without introducing another worker."""

        with self._lock:
            if self._sync_active or (
                self._thread is not None and self._thread.is_alive()
            ):
                return _failure(
                    "production_runner_already_started",
                    "The production application runner is already active.",
                )
            self._failure = None
            self._finished.clear()
            self._sync_active = True
            if self._composition.prepare_control_before_run:
                self._services.control.prepare_run()
        try:
            self._controller.run_production(
                self._source,
                services=self._services,
                options=self._composition.options,
            )
        except Exception as exc:
            record_runtime_event("production_loop_exception", error=exc)
            with self._lock:
                self._failure = exc
        finally:
            with self._lock:
                self._sync_active = False
                failure = self._failure
            self._finished.set()
        if failure is not None:
            return _failure(
                "production_runner_failed",
                "The production conversation loop exited with an error.",
                cause=failure,
            )
        return CommandResult(True)

    def start(self) -> CommandResult[None]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return _failure(
                    "production_runner_already_started",
                    "The production application runner is already active.",
                )
            self._failure = None
            self._finished.clear()
            if self._composition.prepare_control_before_run:
                self._services.control.prepare_run()
            self._thread = threading.Thread(
                target=self._run,
                name="production-conversation-runner",
                daemon=True,
            )
            self._thread.start()
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        self._services.control.request_stop()
        with self._lock:
            thread = self._thread
        if thread is None:
            return CommandResult(True)
        if thread is threading.current_thread():
            return _failure(
                "production_runner_self_join",
                "The production application runner cannot join its own thread.",
            )
        thread.join(timeout=self._stop_timeout_seconds)
        if thread.is_alive():
            return _failure(
                "production_runner_stop_timeout",
                "The production conversation loop did not stop within the configured timeout.",
            )
        with self._lock:
            failure = self._failure
            self._thread = None
        if failure is not None:
            return _failure(
                "production_runner_failed",
                "The production conversation loop exited with an error.",
                cause=failure,
            )
        return CommandResult(True)

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def _run(self) -> None:
        try:
            self._controller.run_production(
                self._source,
                services=self._services,
                options=self._composition.options,
            )
        except BaseException as exc:
            record_runtime_event("production_loop_exception", error=exc)
            with self._lock:
                self._failure = exc
        finally:
            self._finished.set()


def _failure(
    category: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> CommandResult[None]:
    return CommandResult(
        False,
        failure=RuntimeFailure(category, message, cause=cause),
    )


__all__ = [
    "IncompleteProductionCompositionError",
    "ProductionApplicationComposition",
    "ProductionApplicationRunner",
    "ProductionConversationController",
    "ProductionLoopControl",
    "ProductionServiceGraph",
]
