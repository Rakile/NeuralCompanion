"""Concrete production ownership for the finite Identity Relay boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from core import chat_providers
from core.runtime.identity_relay import (
    IdentityRelayArtifactCapabilities,
    IdentityRelayProviderPort,
    IdentityRelayService,
)
from core.runtime.lifecycle import WorkerSupervisor


@runtime_checkable
class IdentityRelayArtifactController(Protocol):
    """Exact addon operations used by production Relay coordination."""

    def set_persona_identity_ref(
        self,
        artifact_ref: str,
        *,
        notify: bool = True,
    ) -> object: ...

    def capture_mode(self) -> object: ...

    def capture_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...

    def prepare_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...

    def render_judge_request(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...

    def finalize_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...

    def restore_persisted_snapshot(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object: ...


class IdentityRelayTokenCounter(Protocol):
    def count(
        self,
        context: object,
        messages: Sequence[Mapping[str, object]],
    ) -> int: ...


class FrozenIdentityRelayTokenCounter:
    """Count against the immutable provider context accepted for the turn."""

    __slots__ = ()

    def count(
        self,
        context: object,
        messages: Sequence[Mapping[str, object]],
    ) -> int:
        return int(chat_providers.count_frozen_chat_tokens(context, messages))


class IdentityRelayProviderDispatch(Protocol):
    def claim(self, state: object, request: object, kind: str) -> None: ...


class IdentityRelayEmbeddingOwner(Protocol):
    def embed(self, *args: object, **kwargs: object) -> object: ...


class IdentityRelayDeletionOwner(Protocol):
    def delete_transaction(self, artifact_ref: str, commit: object) -> object: ...

    def purge_derivatives(self, artifact_ref: str) -> object: ...


class ProductionIdentityRelayArtifactControllerBinding:
    """Core-owned, lifecycle-bound access to the focused artifact controller.

    The binding exists before addon discovery.  The focused addon attaches its
    controller exactly once for its lifecycle, and the production Relay keeps
    calling this stable owner rather than discovering the addon or retaining a
    UI object through a service locator.
    """

    __slots__ = ("_controller", "_generation", "_lock")

    _DISCONNECTED_MODE = MappingProxyType(
        {
            "connected": False,
            "enabled": False,
            "artifact_ref": "",
            "artifact_hash": "",
            "connection_revision": 0,
        }
    )

    def __init__(self) -> None:
        self._lock = RLock()
        self._controller: IdentityRelayArtifactController | None = None
        self._generation = 0

    @property
    def bound(self) -> bool:
        with self._lock:
            return self._controller is not None

    def bind(
        self,
        controller: IdentityRelayArtifactController,
    ) -> "IdentityRelayArtifactControllerLease":
        _validate_artifact_controller(controller)
        with self._lock:
            if self._controller is not None:
                raise RuntimeError(
                    "Identity Relay artifact controller is already bound."
                )
            self._generation += 1
            generation = self._generation
            self._controller = controller
        return IdentityRelayArtifactControllerLease(self, controller, generation)

    def set_persona_identity_ref(
        self,
        artifact_ref: str,
        *,
        notify: bool = True,
    ) -> object:
        return self._require_controller().set_persona_identity_ref(
            artifact_ref,
            notify=notify,
        )

    def capture_mode(self) -> object:
        controller = self._controller_snapshot()
        if controller is None:
            return self._DISCONNECTED_MODE
        return controller.capture_mode()

    def capture_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._require_controller().capture_turn(payload)

    def prepare_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._require_controller().prepare_turn(payload)

    def render_judge_request(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._require_controller().render_judge_request(payload)

    def finalize_turn(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._require_controller().finalize_turn(payload)

    def restore_persisted_snapshot(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        return self._require_controller().restore_persisted_snapshot(payload)

    def _controller_snapshot(self) -> IdentityRelayArtifactController | None:
        with self._lock:
            return self._controller

    def _require_controller(self) -> IdentityRelayArtifactController:
        controller = self._controller_snapshot()
        if controller is None:
            raise RuntimeError(
                "Identity Relay artifact controller is not attached to its focused addon."
            )
        return controller

    def _release(
        self,
        controller: IdentityRelayArtifactController,
        generation: int,
    ) -> bool:
        with self._lock:
            if (
                self._controller is not controller
                or self._generation != generation
            ):
                return False
            self._controller = None
            return True


class IdentityRelayArtifactControllerLease:
    """Idempotent lifecycle lease for one focused artifact controller."""

    __slots__ = ("_closed", "_controller", "_generation", "_owner")

    def __init__(
        self,
        owner: ProductionIdentityRelayArtifactControllerBinding,
        controller: IdentityRelayArtifactController,
        generation: int,
    ) -> None:
        self._owner = owner
        self._controller = controller
        self._generation = int(generation)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        return self._owner._release(self._controller, self._generation)


class ProductionIdentityRelayProviderDispatchOwner:
    """Own the exact accepted-turn dispatch admission operation."""

    __slots__ = ("_claim",)

    def __init__(self, claim: Callable[[object, object, str], object]) -> None:
        if not callable(claim):
            raise TypeError("Identity Relay provider dispatch requires a callable.")
        self._claim = claim

    def claim(self, state: object, request: object, kind: str) -> None:
        self._claim(state, request, str(kind or ""))


class ProductionIdentityRelayEmbeddingOwner:
    """Own the runtime embedding operation used by Identity Relay."""

    __slots__ = ("_embed",)

    def __init__(self, embed: Callable[..., object]) -> None:
        if not callable(embed):
            raise TypeError("Identity Relay embedding requires a callable.")
        self._embed = embed

    def embed(self, *args: object, **kwargs: object) -> object:
        return self._embed(*args, **kwargs)


class ProductionIdentityRelayDeletionOwner:
    """Own deletion admission and derivative cleanup operations."""

    __slots__ = ("_delete_transaction", "_purge_derivatives")

    def __init__(
        self,
        *,
        delete_transaction: Callable[[str, object], object],
        purge_derivatives: Callable[[str], object],
    ) -> None:
        if not callable(delete_transaction) or not callable(purge_derivatives):
            raise TypeError("Identity Relay deletion requires two callables.")
        self._delete_transaction = delete_transaction
        self._purge_derivatives = purge_derivatives

    def delete_transaction(self, artifact_ref: str, commit: object) -> object:
        return self._delete_transaction(str(artifact_ref or ""), commit)

    def purge_derivatives(self, artifact_ref: str) -> object:
        return self._purge_derivatives(str(artifact_ref or ""))


@dataclass(frozen=True, slots=True)
class ProductionIdentityRelayRuntimeOwners:
    """The complete core-owned platform boundary for Identity Relay."""

    artifacts: ProductionIdentityRelayArtifactControllerBinding
    provider_dispatch: IdentityRelayProviderDispatch
    embedding: IdentityRelayEmbeddingOwner
    deletion: IdentityRelayDeletionOwner

    def __post_init__(self) -> None:
        if not isinstance(
            self.artifacts,
            ProductionIdentityRelayArtifactControllerBinding,
        ):
            raise TypeError(
                "Identity Relay runtime owners require the core artifact binding."
            )
        if not isinstance(
            self.provider_dispatch,
            ProductionIdentityRelayProviderDispatchOwner,
        ):
            raise TypeError("Identity Relay runtime owners require provider dispatch.")
        if not isinstance(
            self.embedding,
            ProductionIdentityRelayEmbeddingOwner,
        ):
            raise TypeError("Identity Relay runtime owners require embedding ownership.")
        if not isinstance(
            self.deletion,
            ProductionIdentityRelayDeletionOwner,
        ):
            raise TypeError("Identity Relay runtime owners require deletion ownership.")


class ProductionIdentityRelayArtifactOwner:
    """Adapt the addon controller's policy-preserving v2 Relay operations."""

    __slots__ = ("_capabilities", "_controller")

    def __init__(self, controller: IdentityRelayArtifactController) -> None:
        self._controller = controller
        self._capabilities = IdentityRelayArtifactCapabilities(
            capture_mode=controller.capture_mode,
            capture_turn=self.capture_turn,
            prepare_turn=self.prepare_turn,
            render_judge_request=self.render_judge_request,
            finalize_turn=self.finalize_turn,
            restore_persisted_snapshot=self.restore_persisted_snapshot,
        )

    @property
    def capabilities(self) -> IdentityRelayArtifactCapabilities:
        return self._capabilities

    @property
    def controller(self) -> IdentityRelayArtifactController:
        return self._controller

    def connect_artifact(self, artifact_ref: str, *, notify: bool = True) -> object:
        """Let the addon resolve, load, attest, and connect the exact artifact."""

        return self._controller.set_persona_identity_ref(
            str(artifact_ref or ""),
            notify=bool(notify),
        )

    def capture_turn(self, payload: Mapping[str, object]) -> object:
        return self._controller.capture_turn(_capability_payload(payload))

    def prepare_turn(self, payload: Mapping[str, object]) -> object:
        return self._controller.prepare_turn(_capability_payload(payload))

    def render_judge_request(self, payload: Mapping[str, object]) -> object:
        return self._controller.render_judge_request(_capability_payload(payload))

    def finalize_turn(self, payload: Mapping[str, object]) -> object:
        return self._controller.finalize_turn(_capability_payload(payload))

    def restore_persisted_snapshot(
        self,
        payload: Mapping[str, object],
    ) -> object:
        return self._controller.restore_persisted_snapshot(
            _capability_payload(payload)
        )


class ProductionIdentityRelayOwner:
    """Construct Relay coordination from named, finite production collaborators."""

    __slots__ = (
        "_artifacts",
        "_deletion",
        "_embedding",
        "_provider_dispatch",
        "_service",
        "_token_counter",
    )

    def __init__(
        self,
        *,
        artifacts: ProductionIdentityRelayArtifactOwner,
        providers: IdentityRelayProviderPort,
        workers: WorkerSupervisor,
        provider_dispatch: IdentityRelayProviderDispatch | None,
        embedding: IdentityRelayEmbeddingOwner,
        deletion: IdentityRelayDeletionOwner,
        token_counter: IdentityRelayTokenCounter | None = None,
        logger: Callable[[str], object] | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._token_counter = token_counter or FrozenIdentityRelayTokenCounter()
        self._provider_dispatch = provider_dispatch
        self._embedding = embedding
        self._deletion = deletion
        self._service = IdentityRelayService(
            providers=providers,
            workers=workers,
            artifacts=artifacts.capabilities,
            count_tokens=self._count_tokens,
            provider_dispatch=(
                self._claim_provider_dispatch
                if provider_dispatch is not None
                else None
            ),
            logger=logger,
            runtime_embedding=embedding.embed,
            runtime_delete_transaction=deletion.delete_transaction,
            runtime_derivative_purge=deletion.purge_derivatives,
            runtime_artifact_controller=artifacts.controller,
        )

    @property
    def service(self) -> IdentityRelayService:
        return self._service

    @property
    def artifacts(self) -> ProductionIdentityRelayArtifactOwner:
        return self._artifacts

    def install_addon_runtime(self, host: object) -> bool:
        return self._service.install_addon_runtime(host)

    def _count_tokens(
        self,
        context: object,
        messages: Sequence[Mapping[str, object]],
    ) -> int:
        return self._token_counter.count(context, messages)

    def _claim_provider_dispatch(
        self,
        state: object,
        request: object,
        kind: str,
    ) -> None:
        provider_dispatch = self._provider_dispatch
        if provider_dispatch is not None:
            provider_dispatch.claim(state, request, kind)


def _capability_payload(value: Mapping[str, object]) -> dict[str, object]:
    """Preserve the JSON-like payload shape used by the legacy addon boundary."""

    return {
        str(key): _capability_value(
            item,
            lists=str(key) in {"frozen_provider", "query", "snapshot"},
        )
        for key, item in value.items()
    }


def _capability_value(value: object, *, lists: bool = False) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _capability_value(
                item,
                lists=(lists or str(key) in {"frozen_provider", "query", "snapshot"}),
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        items = tuple(_capability_value(item, lists=lists) for item in value)
        return list(items) if lists else items
    return value


def _validate_artifact_controller(controller: object) -> None:
    if not isinstance(controller, IdentityRelayArtifactController):
        raise TypeError(
            "Identity Relay artifact controller does not satisfy its finite protocol."
        )


__all__ = [
    "IdentityRelayArtifactController",
    "IdentityRelayDeletionOwner",
    "IdentityRelayEmbeddingOwner",
    "IdentityRelayProviderDispatch",
    "IdentityRelayTokenCounter",
    "IdentityRelayArtifactControllerLease",
    "FrozenIdentityRelayTokenCounter",
    "ProductionIdentityRelayArtifactControllerBinding",
    "ProductionIdentityRelayArtifactOwner",
    "ProductionIdentityRelayDeletionOwner",
    "ProductionIdentityRelayEmbeddingOwner",
    "ProductionIdentityRelayOwner",
    "ProductionIdentityRelayProviderDispatchOwner",
    "ProductionIdentityRelayRuntimeOwners",
]
