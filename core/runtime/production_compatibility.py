"""Finite compatibility adapters for the remaining production edges.

Each adapter implements one existing runtime protocol.  The callbacks remain
explicit so final production composition can retire them independently without
introducing a dispatch table or service locator.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from core.runtime.identity_relay import IdentityRelaySnapshotRegistry


AssistantCommitCallback = Callable[..., Mapping[str, object] | None]
TransactionCurrentCallback = Callable[..., bool]
AddonContextCallback = Callable[..., object]


class ProductionRelayMetadataCompatibility:
    """Use the canonical Relay registry validator for durable turn metadata."""

    __slots__ = ()

    def sanitize(self, value: object) -> Mapping[str, object] | None:
        metadata = IdentityRelaySnapshotRegistry.sanitize_metadata(value)
        return metadata.as_mapping() if metadata is not None else None


class ProductionChatViewCompatibility:
    """Publish the legacy chat-rebuild notice through one named edge."""

    __slots__ = ("_request_rebuild",)

    def __init__(self, request_rebuild: Callable[[], object]) -> None:
        if not callable(request_rebuild):
            raise TypeError("Chat rebuild publication requires a callable.")
        self._request_rebuild = request_rebuild

    def request_rebuild(self) -> None:
        self._request_rebuild()


class ProductionTransactionCompatibility:
    """Adapt finite Normal Chat transaction maintenance operations."""

    __slots__ = ("_discard", "_is_current", "_prune")

    def __init__(
        self,
        *,
        prune: Callable[[], object],
        discard: Callable[[str], object],
        is_current: TransactionCurrentCallback,
    ) -> None:
        if not callable(prune) or not callable(discard) or not callable(is_current):
            raise TypeError("Transaction maintenance requires three callables.")
        self._prune = prune
        self._discard = discard
        self._is_current = is_current

    def prune(self) -> None:
        self._prune()

    def discard(self, transaction_id: str) -> None:
        self._discard(str(transaction_id or ""))

    def is_current(
        self,
        transaction_id: str,
        *,
        session_generation: int | None = None,
    ) -> bool:
        return bool(
            self._is_current(
                str(transaction_id or ""),
                session_generation=session_generation,
            )
        )


class ProductionAssistantCommitCompatibility:
    """Commit an assistant turn through the accepted transaction callback."""

    __slots__ = ("_commit",)

    def __init__(self, commit: AssistantCommitCallback) -> None:
        if not callable(commit):
            raise TypeError("Assistant history commit requires a callable.")
        self._commit = commit

    def commit(
        self,
        text: str,
        *,
        metadata: Mapping[str, object],
        expected_session_generation: int | None,
        expected_turn_id: str | None,
    ) -> dict[str, object] | None:
        committed = self._commit(
            str(text or ""),
            metadata=copy.deepcopy(dict(metadata or {})),
            expected_session_generation=expected_session_generation,
            expected_turn_id=(
                str(expected_turn_id) if expected_turn_id is not None else None
            ),
        )
        if committed is None:
            return None
        if not isinstance(committed, Mapping):
            raise TypeError("Assistant history commit must return a mapping or None.")
        return copy.deepcopy(dict(committed))


class ProductionMemoryTriggerCompatibility:
    """Expose only the two automatic conversation-memory triggers."""

    __slots__ = ("_archive_long_term", "_update_continuity")

    def __init__(
        self,
        *,
        update_continuity: Callable[[], object],
        archive_long_term: Callable[[], object],
    ) -> None:
        if not callable(update_continuity) or not callable(archive_long_term):
            raise TypeError("Automatic memory triggers require two callables.")
        self._update_continuity = update_continuity
        self._archive_long_term = archive_long_term

    def maybe_update_continuity(self) -> None:
        self._update_continuity()

    def maybe_archive_long_term(self) -> None:
        self._archive_long_term()


class ProductionScreenCaptureCompatibility:
    """Capture one screen-source snapshot without exposing sensory dispatch."""

    __slots__ = ("_capture",)

    def __init__(self, capture: Callable[[], Mapping[str, object] | None]) -> None:
        if not callable(capture):
            raise TypeError("Screen capture requires a callable.")
        self._capture = capture

    def capture(self) -> Mapping[str, object] | None:
        snapshot = self._capture()
        if snapshot is None:
            return None
        if not isinstance(snapshot, Mapping):
            raise TypeError("Screen capture must return a mapping or None.")
        return copy.deepcopy(dict(snapshot))


class ProductionUserImagePolicyCompatibility:
    """Adapt the current screen-auto-attach and source-selection policy."""

    __slots__ = ("_auto_attach_screen", "_source_enabled")

    def __init__(
        self,
        *,
        auto_attach_screen: Callable[[], bool],
        source_enabled: Callable[[str], bool],
    ) -> None:
        if not callable(auto_attach_screen) or not callable(source_enabled):
            raise TypeError("User image policy requires two callables.")
        self._auto_attach_screen = auto_attach_screen
        self._source_enabled = source_enabled

    def auto_attach_screen(self) -> bool:
        return bool(self._auto_attach_screen())

    def source_enabled(self, source: str) -> bool:
        return bool(self._source_enabled(str(source or "")))


class ProductionIdentityRelaySessionCompatibility:
    """Persist the addon-owned Identity Relay chat-session document."""

    __slots__ = ("_export_session", "_import_session", "_reset_session")

    def __init__(
        self,
        *,
        reset_session: Callable[[], object],
        export_session: Callable[[], Mapping[str, object] | None],
        import_session: Callable[[Mapping[str, object]], object],
    ) -> None:
        if (
            not callable(reset_session)
            or not callable(export_session)
            or not callable(import_session)
        ):
            raise TypeError("Identity Relay session persistence requires three callables.")
        self._reset_session = reset_session
        self._export_session = export_session
        self._import_session = import_session

    def reset_session(self) -> None:
        self._reset_session()

    def export_session(self) -> Mapping[str, object] | None:
        payload = self._export_session()
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise TypeError("Identity Relay session export must return a mapping or None.")
        return copy.deepcopy(dict(payload))

    def import_session(self, payload: Mapping[str, object]) -> None:
        self._import_session(copy.deepcopy(dict(payload or {})))


class ProductionIdentityRelayProviderCompatibility:
    """Claim one exact Relay provider dispatch through the transaction edge."""

    __slots__ = ("_claim",)

    def __init__(self, claim: Callable[[object, object, str], object]) -> None:
        if not callable(claim):
            raise TypeError("Identity Relay provider dispatch requires a callable.")
        self._claim = claim

    def claim(self, state: object, request: object, kind: str) -> None:
        self._claim(state, request, str(kind or ""))


class ProductionIdentityRelayEmbeddingCompatibility:
    """Expose the exact embedding operation installed into Relay runtime."""

    __slots__ = ("_embed",)

    def __init__(self, embed: Callable[..., object]) -> None:
        if not callable(embed):
            raise TypeError("Identity Relay embedding requires a callable.")
        self._embed = embed

    def embed(self, *args: object, **kwargs: object) -> object:
        return self._embed(*args, **kwargs)


class ProductionIdentityRelayDeletionCompatibility:
    """Expose deletion admission and derivative purge as named operations."""

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


class ProductionAddonManagerCompatibility:
    """Bind the late addon manager and collect only addon chat contexts."""

    __slots__ = ("_bind_manager_getter", "_collect_contexts")

    def __init__(
        self,
        *,
        bind_manager_getter: Callable[[Callable[[], object | None]], Callable[[], None]],
        collect_contexts: AddonContextCallback,
    ) -> None:
        if not callable(bind_manager_getter) or not callable(collect_contexts):
            raise TypeError("Addon manager compatibility requires two callables.")
        self._bind_manager_getter = bind_manager_getter
        self._collect_contexts = collect_contexts

    def bind_addon_manager_getter(
        self,
        getter: Callable[[], object | None],
    ) -> Callable[[], None]:
        if not callable(getter):
            raise TypeError("Addon manager binding requires a callable getter.")
        unbind = self._bind_manager_getter(getter)
        if not callable(unbind):
            raise TypeError("Addon manager binding must return an unbind callable.")
        return unbind

    def collect_addon_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> object:
        frozen_history = [copy.deepcopy(dict(message)) for message in history]
        return self._collect_contexts(
            frozen_history,
            request_kind=(
                str(request_kind) if request_kind is not None else None
            ),
            excluded_addon_ids=tuple(
                str(addon_id or "") for addon_id in excluded_addon_ids
            ),
            **({"document_memory": document_memory} if document_memory is not None else {}),
            **({"document_package_id": document_package_id} if document_package_id else {}),
        )


@dataclass(frozen=True, slots=True)
class ProductionConversationCompatibility:
    """All finite compatibility ports needed by production conversation owners."""

    relay_metadata: ProductionRelayMetadataCompatibility
    chat_view: ProductionChatViewCompatibility
    transactions: ProductionTransactionCompatibility
    committer: ProductionAssistantCommitCompatibility
    memory: ProductionMemoryTriggerCompatibility
    screen_capture: ProductionScreenCaptureCompatibility
    user_image_policy: ProductionUserImagePolicyCompatibility


@dataclass(frozen=True, slots=True)
class ProductionIdentityRelayCompatibility:
    """All finite compatibility ports needed by production Relay ownership."""

    session: ProductionIdentityRelaySessionCompatibility
    provider_dispatch: ProductionIdentityRelayProviderCompatibility
    embedding: ProductionIdentityRelayEmbeddingCompatibility
    deletion: ProductionIdentityRelayDeletionCompatibility


@dataclass(frozen=True, slots=True)
class ProductionCompatibility:
    """Explicit compatibility input to final production composition."""

    conversation: ProductionConversationCompatibility
    identity_relay: ProductionIdentityRelayCompatibility
    addons: ProductionAddonManagerCompatibility


__all__ = [
    "ProductionAddonManagerCompatibility",
    "ProductionAssistantCommitCompatibility",
    "ProductionChatViewCompatibility",
    "ProductionCompatibility",
    "ProductionConversationCompatibility",
    "ProductionIdentityRelayCompatibility",
    "ProductionIdentityRelayDeletionCompatibility",
    "ProductionIdentityRelayEmbeddingCompatibility",
    "ProductionIdentityRelayProviderCompatibility",
    "ProductionIdentityRelaySessionCompatibility",
    "ProductionMemoryTriggerCompatibility",
    "ProductionRelayMetadataCompatibility",
    "ProductionScreenCaptureCompatibility",
    "ProductionTransactionCompatibility",
    "ProductionUserImagePolicyCompatibility",
]
