"""Typed construction of the production conversation application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.conversation_flow_v2 import (
    ConversationController,
    ConversationPolicy,
    ProductionConversationServices,
    ProductionRunOptions,
    SystemClockRuntime,
    TurnCoordinatorPort,
)
from core.runtime.application_runner import (
    ProductionApplicationComposition,
    ProductionApplicationRunner,
)
from core.runtime.contracts import CommandResult


@dataclass(frozen=True, slots=True)
class _NoMicrophoneSource:
    """Explicit source used by replay/STT-disabled runs."""

    mode: str = "no_microphone"


class ProductionConversationApplication:
    """Create one caller-thread runner for each engine run."""

    def __init__(
        self,
        *,
        controller: ConversationController,
        services: ProductionConversationServices,
        options: ProductionRunOptions | None = None,
        prepare_control_before_run: bool = True,
    ) -> None:
        missing = services.missing_domains()
        if missing:
            raise ValueError(
                "Production conversation services are incomplete: "
                + ", ".join(missing)
            )
        self._controller = controller
        self._services = services
        self._options = options
        self._prepare_control_before_run = bool(prepare_control_before_run)

    def run(self, source: object | None) -> CommandResult[None]:
        runner = ProductionApplicationRunner(
            ProductionApplicationComposition(
                controller=self._controller,
                source=source if source is not None else _NoMicrophoneSource(),
                services=self._services,
                options=self._options,
                # ProductionStartupEnvironmentPort reset the stop gate before
                # any blocking startup work. Reopening it here would discard a
                # Stop requested during avatar, TTS, or microphone startup.
                prepare_control_before_run=self._prepare_control_before_run,
            )
        )
        return runner.run_sync()


def build_production_conversation_application(
    runtime_config: Mapping[str, object],
    *,
    turns: TurnCoordinatorPort,
    services: ProductionConversationServices,
    options: ProductionRunOptions | None = None,
    clock=None,
) -> ProductionConversationApplication:
    """Build the production controller without a legacy engine adapter."""

    control = services.control
    controller = ConversationController(
        policy=ConversationPolicy.from_runtime_config(runtime_config),
        runtime=SystemClockRuntime(
            stop_requested=control.controls.stop.is_set,
            clock=clock,
        ),
        turns=turns,
        production_services=services,
    )
    return ProductionConversationApplication(
        controller=controller,
        services=services,
        options=options,
        prepare_control_before_run=False,
    )


__all__ = [
    "ProductionConversationApplication",
    "build_production_conversation_application",
]
