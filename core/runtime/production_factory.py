"""Concrete, explicit construction of the default production application host."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from core.runtime.composition import RuntimeFoundation, compose_runtime_foundation
from core.runtime.config import RuntimeConfigService
from core.runtime.conversation import ConversationService
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.memory_embeddings import JsonRequest
from core.runtime.production_application import (
    ProductionApplicationDependencies,
    build_production_application,
)
from core.runtime.production_bootstrap import ProductionBootstrap
from core.runtime.production_composer import (
    ProductionApplicationComposer,
    ProductionApplicationCompositionState,
    ProductionCompositionRoots,
)
from core.runtime.production_host import ProductionApplicationHost
from core.runtime.production_identity import (
    IdentityRelayTokenCounter,
    ProductionIdentityRelayArtifactOwner,
    ProductionIdentityRelayOwner,
    ProductionIdentityRelayRuntimeOwners,
)
from core.runtime.production_memory import (
    ProductionMemoryOwner,
)
from core.runtime.production_memory_provider import ProductionMemoryProviderAdapter
from core.runtime.production_provider import ProductionProviderOwner
from core.runtime.production_realtime import ProductionRealtimeOwners
from core.runtime.session_resources import SessionResourceGuard


@dataclass(frozen=True, slots=True)
class ProductionFactoryInputs:
    """All platform leaves required to construct the real production graph.

    None of these ports has a production no-op fallback.  A platform that
    cannot provide one receives one deterministic error naming every missing
    port before any runtime owner or worker is created.
    """

    app_root: str | Path
    initial_config: Mapping[str, object]
    realtime: ProductionRealtimeOwners | None = None
    identity_runtime: ProductionIdentityRelayRuntimeOwners | None = None
    application_composer: ProductionApplicationComposer | None = None
    identity_token_counter: IdentityRelayTokenCounter | None = None
    memory_embedding_request_json: JsonRequest | None = None
    memory_refresh_assets: Callable[[object], object] | None = None
    logger: Callable[[str], object] = print

    def __post_init__(self) -> None:
        required = {
            "realtime": self.realtime,
            "identity_runtime": self.identity_runtime,
            "application_composer": self.application_composer,
        }
        missing = tuple(name for name, value in required.items() if value is None)
        if missing:
            raise TypeError(
                "Missing required production ports: " + ", ".join(missing)
            )
        if not isinstance(self.initial_config, Mapping):
            raise TypeError("initial_config must be a mapping.")
        if not callable(self.logger):
            raise TypeError("logger must be callable.")


class DefaultProductionHostFactory:
    """Build and retain exactly one complete set of production owners."""

    __slots__ = ("_host", "_inputs", "_owners")

    def __init__(self, inputs: ProductionFactoryInputs) -> None:
        if not isinstance(inputs, ProductionFactoryInputs):
            raise TypeError("Default production factory requires ProductionFactoryInputs.")
        self._inputs = inputs
        self._host: ProductionApplicationHost | None = None
        self._owners: tuple[object, ...] = ()

    def __call__(self) -> ProductionApplicationHost:
        current = self._host
        if current is not None:
            return current

        inputs = self._inputs
        realtime = _required(inputs.realtime, "realtime")
        identity_runtime = _required(inputs.identity_runtime, "identity_runtime")
        application_composer = _required(
            inputs.application_composer,
            "application_composer",
        )

        config = RuntimeConfigService(dict(inputs.initial_config))
        workers = WorkerSupervisor()
        conversation = ConversationService()
        session_guard = SessionResourceGuard(conversation)
        provider_owner = ProductionProviderOwner(
            config,
            workers=workers,
            worker_lease=conversation.session_lease,
            logger=inputs.logger,
        )
        memory_provider = ProductionMemoryProviderAdapter(provider_owner)
        memory_owner = ProductionMemoryOwner(
            config,
            conversation,
            workers,
            memory_provider,
            runtime_dir=Path(inputs.app_root) / "runtime",
            session_guard=session_guard,
            embedding_request_json=inputs.memory_embedding_request_json,
            refresh_assets=inputs.memory_refresh_assets,
            logger=inputs.logger,
        )
        artifact_owner = ProductionIdentityRelayArtifactOwner(
            identity_runtime.artifacts
        )
        identity_owner = ProductionIdentityRelayOwner(
            artifacts=artifact_owner,
            providers=provider_owner.service,
            workers=workers,
            # The core Relay binding and cancellation token are the exact
            # Normal Chat dispatch admission. The desktop compatibility
            # registry is intentionally not a second transaction mirror.
            provider_dispatch=None,
            embedding=identity_runtime.embedding,
            deletion=identity_runtime.deletion,
            token_counter=inputs.identity_token_counter,
            logger=inputs.logger,
        )
        prepared = realtime.prepare()
        foundation = compose_runtime_foundation(
            dict(inputs.initial_config),
            config_service=config,
            worker_supervisor=workers,
            conversation_service=conversation,
            provider_service=provider_owner.service,
            session_resource_guard=session_guard,
            memory_service=memory_owner.service,
            memory_admin_service=memory_owner.admin,
            identity_relay_service=identity_owner.service,
            speech_input_capabilities=prepared.speech_input_capabilities,
            speech_input_tuning=prepared.speech_input_tuning,
            speech_input_logger=prepared.speech_input_logger,
            speech_output_capabilities=prepared.speech_output_capabilities,
            playback_device=prepared.playback_device,
            replay_playback_capabilities=None,
            visual_capabilities=prepared.visual_capabilities,
            visual_request_id_factory=prepared.visual_request_id_factory,
            sensory_capabilities=prepared.sensory_capabilities,
            sensory_registry=prepared.sensory_registry,
            interaction_capabilities=prepared.interaction_capabilities,
            interaction_queue_size=prepared.interaction_queue_size,
            replay_voice_resolver=prepared.replay_voice_resolver,
            replay_trace=prepared.replay_trace,
            runtime_dir=Path(inputs.app_root) / "runtime",
        )
        application_state = application_composer.compose(
            ProductionCompositionRoots(
                foundation=foundation,
                memory=memory_owner,
            )
        )
        if not isinstance(application_state, ProductionApplicationCompositionState):
            raise TypeError(
                "Production application composer must return "
                "ProductionApplicationCompositionState."
            )
        host = build_production_application(
            ProductionApplicationDependencies(
                foundation=foundation,
                addon_owners=application_state.addon_owners,
                run_owner=application_state.run_owner,
                stop_owner=application_state.stop_owner,
                bindings=application_state.bindings,
            )
        )
        self._owners = (
            config,
            workers,
            conversation,
            session_guard,
            provider_owner,
            memory_owner,
            artifact_owner,
            identity_owner,
            realtime,
            application_state,
            *application_state.retained_owners,
        )
        self._host = host
        return host


def build_default_production_bootstrap(
    inputs: ProductionFactoryInputs,
) -> ProductionBootstrap:
    """Return the process bootstrap for one fully declared production graph."""

    return ProductionBootstrap(DefaultProductionHostFactory(inputs))


def _required(value, name: str):
    if value is None:
        raise RuntimeError(f"Required production port became unavailable: {name}")
    return value


__all__ = [
    "DefaultProductionHostFactory",
    "ProductionFactoryInputs",
    "build_default_production_bootstrap",
]
