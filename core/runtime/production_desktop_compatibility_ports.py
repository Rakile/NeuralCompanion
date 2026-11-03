"""Process-owned ports for the remaining desktop compatibility boundaries.

This module deliberately contains no imports from ``engine`` or ``qt_app``.
Mutable compatibility state is process-owned here, while constructor cycles are
represented by finite bind-once ports that fail when used before composition.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.sensory_source_selection import enabled_source_ids
from core.runtime.production_compatibility import (
    ProductionAddonManagerCompatibility,
    ProductionAssistantCommitCompatibility,
    ProductionChatViewCompatibility,
    ProductionCompatibility,
    ProductionConversationCompatibility,
    ProductionIdentityRelayCompatibility,
    ProductionIdentityRelayDeletionCompatibility,
    ProductionIdentityRelayEmbeddingCompatibility,
    ProductionIdentityRelayProviderCompatibility,
    ProductionIdentityRelaySessionCompatibility,
    ProductionMemoryTriggerCompatibility,
    ProductionRelayMetadataCompatibility,
    ProductionScreenCaptureCompatibility,
    ProductionTransactionCompatibility,
    ProductionUserImagePolicyCompatibility,
)
from core.runtime.production_desktop_identity import (
    ProductionDesktopIdentityDerivatives,
    ProductionDesktopIdentityInputs,
    ProductionDesktopIdentityTransactions,
)
from core.runtime.production_identity import ProductionIdentityRelayRuntimeOwners


class DesktopConversationOwner(Protocol):
    def snapshot(self) -> object: ...

    def message_mappings(self) -> Sequence[Mapping[str, object]]: ...


class DesktopPendingTurnOwner(Protocol):
    def pending_loaded_input_turn(self) -> Mapping[str, object] | None: ...


class DesktopRuntimeConfigOwner(Protocol):
    def snapshot(self) -> object: ...


class DesktopChatViewOwner(Protocol):
    def request_rebuild(self) -> object: ...


class DesktopAssistantCommitOwner(Protocol):
    def commit(
        self,
        text: str,
        *,
        metadata: Mapping[str, object],
        expected_session_generation: int | None,
        expected_turn_id: str | None,
    ) -> Mapping[str, object] | None: ...


class DesktopMemoryTriggerOwner(Protocol):
    def maybe_update_continuity(self) -> object: ...

    def maybe_archive_long_term(self) -> object: ...


class DesktopScreenCaptureOwner(Protocol):
    def capture(self) -> Mapping[str, object] | None: ...


class DesktopIdentityRelaySessionOwner(Protocol):
    def reset_session(self) -> object: ...

    def export_session(self) -> Mapping[str, object] | None: ...

    def import_session(self, payload: Mapping[str, object]) -> object: ...


class ProductionDesktopNormalChatBlocked(RuntimeError):
    """Raised when Relay work loses its accepted Normal Chat transaction."""


class _BindOnce:
    __slots__ = ("_label", "_lock", "_methods", "_owner")

    def __init__(self, label: str, methods: Sequence[str]) -> None:
        self._label = str(label)
        self._methods = tuple(str(method) for method in methods)
        self._lock = threading.Lock()
        self._owner: object | None = None

    def bind(self, owner: object) -> None:
        missing = tuple(
            method
            for method in self._methods
            if not callable(getattr(owner, method, None))
        )
        if missing:
            raise TypeError(
                f"{self._label} is missing required methods: " + ", ".join(missing)
            )
        with self._lock:
            if self._owner is not None:
                raise RuntimeError(f"{self._label} is already bound.")
            self._owner = owner

    def owner(self) -> object:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError(f"{self._label} was used before binding.")
        return owner


class ProductionDesktopConversationBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop conversation owner",
            ("snapshot", "message_mappings"),
        )

    def bind(self, owner: DesktopConversationOwner) -> None:
        self._binding.bind(owner)

    def current_session_generation(self) -> int:
        snapshot = self._binding.owner().snapshot()
        generation = getattr(snapshot, "session_generation", None)
        value = getattr(generation, "value", generation)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                "Conversation snapshot must expose an integer session generation."
            )
        return value

    def message_mappings(self) -> tuple[dict[str, object], ...]:
        messages = self._binding.owner().message_mappings()
        if not isinstance(messages, Sequence):
            raise TypeError("Conversation message mappings must be a sequence.")
        frozen: list[dict[str, object]] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise TypeError("Every conversation message must be a mapping.")
            frozen.append(copy.deepcopy(dict(message)))
        return tuple(frozen)


class ProductionDesktopPendingTurnBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop pending-turn owner",
            ("pending_loaded_input_turn",),
        )

    def bind(self, owner: DesktopPendingTurnOwner) -> None:
        self._binding.bind(owner)

    def snapshot(self) -> Mapping[str, object] | None:
        value = self._binding.owner().pending_loaded_input_turn()
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise TypeError("Pending loaded input turn must be a mapping or None.")
        return copy.deepcopy(dict(value))


class ProductionDesktopRuntimeConfigBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop runtime-config owner",
            ("snapshot",),
        )

    def bind(self, owner: DesktopRuntimeConfigOwner) -> None:
        self._binding.bind(owner)

    def snapshot(self) -> object:
        snapshot = self._binding.owner().snapshot()
        values = getattr(snapshot, "values", None)
        if not isinstance(values, Mapping):
            raise TypeError("Runtime config snapshot must expose mapping values.")
        return snapshot

    def values(self) -> Mapping[str, object]:
        return self.snapshot().values


class ProductionDesktopChatViewBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop chat-view publisher",
            ("request_rebuild",),
        )

    def bind(self, owner: DesktopChatViewOwner) -> None:
        self._binding.bind(owner)

    def request_rebuild(self) -> None:
        self._binding.owner().request_rebuild()


class ProductionDesktopAssistantCommitBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop assistant-commit owner",
            ("commit",),
        )

    def bind(self, owner: DesktopAssistantCommitOwner) -> None:
        self._binding.bind(owner)

    def commit(
        self,
        text: str,
        *,
        metadata: Mapping[str, object],
        expected_session_generation: int | None,
        expected_turn_id: str | None,
    ) -> Mapping[str, object] | None:
        return self._binding.owner().commit(
            text,
            metadata=metadata,
            expected_session_generation=expected_session_generation,
            expected_turn_id=expected_turn_id,
        )


class ProductionDesktopMemoryTriggerBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop memory-trigger owner",
            ("maybe_update_continuity", "maybe_archive_long_term"),
        )

    def bind(self, owner: DesktopMemoryTriggerOwner) -> None:
        self._binding.bind(owner)

    def maybe_update_continuity(self) -> None:
        self._binding.owner().maybe_update_continuity()

    def maybe_archive_long_term(self) -> None:
        self._binding.owner().maybe_archive_long_term()


class ProductionDesktopScreenCaptureBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop screen-capture owner",
            ("capture",),
        )

    def bind(self, owner: DesktopScreenCaptureOwner) -> None:
        self._binding.bind(owner)

    def capture(self) -> Mapping[str, object] | None:
        return self._binding.owner().capture()


class ProductionDesktopIdentityRelaySessionBinding:
    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _BindOnce(
            "Production desktop Identity Relay session owner",
            ("reset_session", "export_session", "import_session"),
        )

    def bind(self, owner: DesktopIdentityRelaySessionOwner) -> None:
        self._binding.bind(owner)

    def reset_session(self) -> None:
        self._binding.owner().reset_session()

    def export_session(self) -> Mapping[str, object] | None:
        return self._binding.owner().export_session()

    def import_session(self, payload: Mapping[str, object]) -> None:
        self._binding.owner().import_session(payload)


class ProductionDesktopAddonManagerBinding:
    """One explicit late addon-manager binding used only for chat contexts."""

    __slots__ = ("_bound_once", "_getter", "_lock", "_runtime_config")

    def __init__(self, runtime_config: ProductionDesktopRuntimeConfigBinding) -> None:
        self._lock = threading.Lock()
        self._runtime_config = runtime_config
        self._getter: Callable[[], object | None] | None = None
        self._bound_once = False

    def bind_getter(
        self,
        getter: Callable[[], object | None],
    ) -> Callable[[], None]:
        if not callable(getter):
            raise TypeError("Addon manager binding requires a callable getter.")
        with self._lock:
            if self._bound_once:
                raise RuntimeError("Production desktop addon manager is already bound.")
            self._bound_once = True
            self._getter = getter

        closed = False

        def unbind() -> None:
            nonlocal closed
            with self._lock:
                if closed:
                    return
                closed = True
                if self._getter is getter:
                    self._getter = None

        return unbind

    def collect_contexts(
        self,
        history: list[Mapping[str, object]],
        *,
        request_kind: str | None = None,
        excluded_addon_ids: Sequence[str] = (),
        document_memory: bool | None = None,
        document_package_id: str | None = None,
    ) -> list[dict[str, object]]:
        manager = self._manager()
        request: dict[str, object] = {
            "messages": _relay_free_messages(history),
            "active_preset_name": str(
                self._runtime_config.values().get("active_preset_name", "") or ""
            ),
        }
        if request_kind is not None:
            request["request_kind"] = str(request_kind)
        if isinstance(document_memory, bool):
            request["_persona_document_memory"] = document_memory
        if document_package_id:
            request["_persona_document_package_id"] = str(document_package_id).strip()

        excluded = {
            str(addon_id or "").strip()
            for addon_id in excluded_addon_ids
            if str(addon_id or "").strip()
        }
        if excluded:
            records = manager.get_loaded_addons()
            results: list[object] = []
            for record in list(records or ()):
                manifest = getattr(record, "manifest", None)
                addon_id = str(getattr(manifest, "id", "") or "").strip()
                if not addon_id or addon_id in excluded:
                    continue
                result = manager.invoke_addon_capability(
                    addon_id,
                    "chat_context.collect",
                    copy.deepcopy(request),
                )
                if result is not None:
                    results.append(result)
        else:
            results = list(
                manager.invoke_all_capabilities(
                    "chat_context.collect",
                    copy.deepcopy(request),
                )
                or ()
            )
        return _normalize_addon_contexts(results)

    def _manager(self) -> object:
        with self._lock:
            getter = self._getter
        if getter is None:
            raise RuntimeError(
                "Production desktop addon manager was used before binding."
            )
        manager = getter()
        if manager is None:
            raise RuntimeError("The bound production addon manager is unavailable.")
        missing = tuple(
            name
            for name in (
                "get_loaded_addons",
                "invoke_addon_capability",
                "invoke_all_capabilities",
            )
            if not callable(getattr(manager, name, None))
        )
        if missing:
            raise TypeError(
                "The production addon manager is missing required methods: "
                + ", ".join(missing)
            )
        return manager


class ProductionDesktopConversationHistory(Sequence[Mapping[str, object]]):
    """Live read-only sequence used by Identity Relay deletion admission."""

    __slots__ = ("_conversation", "_lock")

    def __init__(
        self,
        conversation: ProductionDesktopConversationBinding,
        lock: threading.RLock,
    ) -> None:
        self._conversation = conversation
        self._lock = lock

    def __len__(self) -> int:
        with self._lock:
            return len(self._conversation.message_mappings())

    def __getitem__(self, index):
        with self._lock:
            messages = self._conversation.message_mappings()
        return messages[index]

    def __iter__(self) -> Iterator[Mapping[str, object]]:
        with self._lock:
            messages = self._conversation.message_mappings()
        return iter(messages)


class ProductionDesktopNormalChatTransactions:
    """Process-owned accepted-turn records needed by Relay admission."""

    __slots__ = ("blocked_error", "lock", "registry", "_conversation")

    _TERMINAL = frozenset(
        {"cancelled", "committed", "discarded", "failed", "superseded"}
    )

    def __init__(
        self,
        conversation: ProductionDesktopConversationBinding,
        blocked_error: type[BaseException],
    ) -> None:
        if not isinstance(blocked_error, type) or not issubclass(
            blocked_error, BaseException
        ):
            raise TypeError("Normal Chat blocked_error must be an exception type.")
        self._conversation = conversation
        self.blocked_error = blocked_error
        self.lock = threading.RLock()
        self.registry: dict[str, MutableMapping[str, object]] = {}

    def register(self, transaction: MutableMapping[str, object]) -> str:
        if not isinstance(transaction, MutableMapping):
            raise TypeError("Normal Chat transaction must be a mutable mapping.")
        turn_id = str(transaction.get("turn_id") or "").strip()
        if not turn_id:
            raise ValueError("Normal Chat transaction requires turn_id.")
        generation = transaction.get("session_generation")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise TypeError("Normal Chat transaction requires session_generation.")
        status = str(transaction.get("status") or "").strip()
        if not status:
            raise ValueError("Normal Chat transaction requires status.")
        _require_context_lock("Normal Chat transaction lock", transaction.get("lock"))
        cancel_event = transaction.get("cancel_event")
        if not callable(getattr(cancel_event, "is_set", None)) or not callable(
            getattr(cancel_event, "set", None)
        ):
            raise TypeError("Normal Chat transaction requires a cancellation event.")
        with self.lock:
            if turn_id in self.registry:
                raise RuntimeError(f"Normal Chat transaction {turn_id!r} already exists.")
            self.registry[turn_id] = transaction
        return turn_id

    def prune(self) -> None:
        generation = self._conversation.current_session_generation()
        removed: list[MutableMapping[str, object]] = []
        with self.lock:
            for turn_id, transaction in tuple(self.registry.items()):
                stale = int(transaction["session_generation"]) != generation
                terminal = str(transaction["status"]) in self._TERMINAL
                if not stale and not terminal:
                    continue
                removed.append(self.registry.pop(turn_id))
        for transaction in removed:
            transaction["cancel_event"].set()

    def discard(self, transaction_id: str) -> None:
        turn_id = str(transaction_id or "").strip()
        with self.lock:
            transaction = self.registry.pop(turn_id, None)
        if transaction is not None:
            transaction["cancel_event"].set()

    def is_current(
        self,
        transaction_id: str,
        *,
        session_generation: int | None = None,
    ) -> bool:
        turn_id = str(transaction_id or "").strip()
        current_generation = self._conversation.current_session_generation()
        expected_generation = (
            current_generation
            if session_generation is None
            else int(session_generation)
        )
        with self.lock:
            transaction = self.registry.get(turn_id)
            if transaction is None:
                return False
            return bool(
                int(transaction["session_generation"]) == current_generation
                and int(transaction["session_generation"]) == expected_generation
                and str(transaction["status"]) not in self._TERMINAL
                and not transaction["cancel_event"].is_set()
            )


class ProductionDesktopRelaySnapshots:
    """Process-owned compatibility snapshots used by deletion admission."""

    __slots__ = ("lock", "registry")

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.registry: dict[str, object] = {}

    def publish(self, snapshot_hash: str, snapshot: object) -> None:
        key = str(snapshot_hash or "").strip()
        if not key:
            raise ValueError("Identity Relay snapshot publication requires a hash.")
        with self.lock:
            self.registry[key] = snapshot

    def remove(self, snapshot_hash: str) -> object | None:
        with self.lock:
            return self.registry.pop(str(snapshot_hash or "").strip(), None)

    def clear(self) -> None:
        with self.lock:
            self.registry.clear()


@dataclass(frozen=True, slots=True)
class ProductionDesktopCompatibilityBindings:
    conversation: ProductionDesktopConversationBinding
    pending_turn: ProductionDesktopPendingTurnBinding
    runtime_config: ProductionDesktopRuntimeConfigBinding
    chat_view: ProductionDesktopChatViewBinding
    assistant_commit: ProductionDesktopAssistantCommitBinding
    memory_triggers: ProductionDesktopMemoryTriggerBinding
    screen_capture: ProductionDesktopScreenCaptureBinding
    identity_relay_session: ProductionDesktopIdentityRelaySessionBinding
    addon_manager: ProductionDesktopAddonManagerBinding

    @classmethod
    def create(cls) -> "ProductionDesktopCompatibilityBindings":
        runtime_config = ProductionDesktopRuntimeConfigBinding()
        return cls(
            conversation=ProductionDesktopConversationBinding(),
            pending_turn=ProductionDesktopPendingTurnBinding(),
            runtime_config=runtime_config,
            chat_view=ProductionDesktopChatViewBinding(),
            assistant_commit=ProductionDesktopAssistantCommitBinding(),
            memory_triggers=ProductionDesktopMemoryTriggerBinding(),
            screen_capture=ProductionDesktopScreenCaptureBinding(),
            identity_relay_session=ProductionDesktopIdentityRelaySessionBinding(),
            addon_manager=ProductionDesktopAddonManagerBinding(runtime_config),
        )


class ProductionDesktopCompatibilityPorts:
    """Construct both production compatibility inputs from explicit roots."""

    __slots__ = (
        "bindings",
        "conversation_history_lock",
        "conversation_history",
        "relay_snapshots",
        "transactions",
    )

    def __init__(
        self,
        *,
        bindings: ProductionDesktopCompatibilityBindings,
        blocked_error: type[BaseException],
    ) -> None:
        if not isinstance(bindings, ProductionDesktopCompatibilityBindings):
            raise TypeError("Production desktop compatibility bindings are required.")
        self.bindings = bindings
        self.conversation_history_lock = threading.RLock()
        self.conversation_history = ProductionDesktopConversationHistory(
            bindings.conversation,
            self.conversation_history_lock,
        )
        self.transactions = ProductionDesktopNormalChatTransactions(
            bindings.conversation,
            blocked_error,
        )
        self.relay_snapshots = ProductionDesktopRelaySnapshots()

    @classmethod
    def create(
        cls,
        *,
        blocked_error: type[BaseException],
    ) -> "ProductionDesktopCompatibilityPorts":
        return cls(
            bindings=ProductionDesktopCompatibilityBindings.create(),
            blocked_error=blocked_error,
        )

    def identity_inputs(
        self,
        *,
        request_json: Callable[..., object],
        logger: Callable[[str], object],
        clock: Callable[[], float],
    ) -> ProductionDesktopIdentityInputs:
        for name, callback in (
            ("request_json", request_json),
            ("logger", logger),
            ("clock", clock),
        ):
            if not callable(callback):
                raise TypeError(f"Production desktop Identity Relay {name} is required.")
        return ProductionDesktopIdentityInputs(
            transactions=ProductionDesktopIdentityTransactions(
                registry=self.transactions.registry,
                lock=self.transactions.lock,
                current_session_generation=(
                    self.bindings.conversation.current_session_generation
                ),
                blocked_error=self.transactions.blocked_error,
            ),
            derivatives=ProductionDesktopIdentityDerivatives(
                conversation_history=self.conversation_history,
                conversation_history_lock=self.conversation_history_lock,
                pending_loaded_input_turn=self.bindings.pending_turn.snapshot,
                snapshots=self.relay_snapshots.registry,
                snapshot_lock=self.relay_snapshots.lock,
            ),
            runtime_config=self.bindings.runtime_config.snapshot,
            request_json=request_json,
            logger=logger,
            clock=clock,
        )

    def compatibility(
        self,
        identity: ProductionIdentityRelayRuntimeOwners,
    ) -> ProductionCompatibility:
        if not isinstance(identity, ProductionIdentityRelayRuntimeOwners):
            raise TypeError("Production Identity Relay runtime owners are required.")
        bindings = self.bindings
        return ProductionCompatibility(
            conversation=ProductionConversationCompatibility(
                relay_metadata=ProductionRelayMetadataCompatibility(),
                chat_view=ProductionChatViewCompatibility(
                    bindings.chat_view.request_rebuild
                ),
                transactions=ProductionTransactionCompatibility(
                    prune=self.transactions.prune,
                    discard=self.transactions.discard,
                    is_current=self.transactions.is_current,
                ),
                committer=ProductionAssistantCommitCompatibility(
                    bindings.assistant_commit.commit
                ),
                memory=ProductionMemoryTriggerCompatibility(
                    update_continuity=(
                        bindings.memory_triggers.maybe_update_continuity
                    ),
                    archive_long_term=(
                        bindings.memory_triggers.maybe_archive_long_term
                    ),
                ),
                screen_capture=ProductionScreenCaptureCompatibility(
                    bindings.screen_capture.capture
                ),
                user_image_policy=ProductionUserImagePolicyCompatibility(
                    auto_attach_screen=self._auto_attach_screen,
                    source_enabled=self._source_enabled,
                ),
            ),
            identity_relay=ProductionIdentityRelayCompatibility(
                session=ProductionIdentityRelaySessionCompatibility(
                    reset_session=bindings.identity_relay_session.reset_session,
                    export_session=bindings.identity_relay_session.export_session,
                    import_session=bindings.identity_relay_session.import_session,
                ),
                provider_dispatch=ProductionIdentityRelayProviderCompatibility(
                    identity.provider_dispatch.claim
                ),
                embedding=ProductionIdentityRelayEmbeddingCompatibility(
                    identity.embedding.embed
                ),
                deletion=ProductionIdentityRelayDeletionCompatibility(
                    delete_transaction=identity.deletion.delete_transaction,
                    purge_derivatives=identity.deletion.purge_derivatives,
                ),
            ),
            addons=ProductionAddonManagerCompatibility(
                bind_manager_getter=bindings.addon_manager.bind_getter,
                collect_contexts=bindings.addon_manager.collect_contexts,
            ),
        )

    def _auto_attach_screen(self) -> bool:
        values = self.bindings.runtime_config.values()
        return bool(values.get("screen_source_auto_attach_next_user_turn", False))

    def _source_enabled(self, source: str) -> bool:
        wanted = str(source or "").strip()
        if not wanted:
            return False
        values = self.bindings.runtime_config.values()
        return wanted in enabled_source_ids(
            values.get("sensory_feedback_source", "off"),
            (wanted,),
        )


def _require_context_lock(name: str, value: object) -> None:
    if not callable(getattr(value, "__enter__", None)) or not callable(
        getattr(value, "__exit__", None)
    ):
        raise TypeError(f"{name} must be a context-manager lock.")


def _relay_free_messages(
    history: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for item in history:
        if not isinstance(item, Mapping):
            raise TypeError("Addon chat history entries must be mappings.")
        message = copy.deepcopy(dict(item))
        message.pop("identity_relay", None)
        messages.append(message)
    return messages


def _normalize_addon_contexts(results: Sequence[object]) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for result in results:
        current_turn_context = ""
        current_turn_image = ""
        if isinstance(result, str):
            text = result.strip()
            debug: dict[str, object] = {}
        elif isinstance(result, Mapping):
            text = str(result.get("context") or "").strip()
            current_turn_context = result.get("current_turn_context", "")
            if not isinstance(current_turn_context, str):
                raise TypeError("Addon current-turn context must be a string.")
            current_turn_context = current_turn_context.strip()
            current_turn_image = result.get("current_turn_image", "")
            if not isinstance(current_turn_image, str):
                raise TypeError("Addon current-turn image must be a string.")
            if current_turn_image and not current_turn_image.startswith("data:image/jpeg;base64,"):
                raise ValueError("Addon current-turn image must be an inline JPEG image.")
            raw_debug = result.get("debug")
            if raw_debug is None:
                debug = {}
            elif isinstance(raw_debug, Mapping):
                debug = copy.deepcopy(dict(raw_debug))
            else:
                raise TypeError("Addon chat context debug data must be a mapping.")
        else:
            raise TypeError("Addon chat contexts must be strings or mappings.")
        if text or current_turn_context or current_turn_image:
            context = {"context": text, "debug": debug}
            if isinstance(result, Mapping):
                from core.runtime.document_context import DocumentContextTicket
                ticket = result.get("_nc_document_ticket")
                if isinstance(ticket, DocumentContextTicket):
                    context["_nc_document_ticket"] = ticket
            if current_turn_context:
                context["current_turn_context"] = current_turn_context
            if current_turn_image:
                context["current_turn_image"] = current_turn_image
            contexts.append(context)
    return contexts


__all__ = [
    "DesktopAssistantCommitOwner",
    "DesktopChatViewOwner",
    "DesktopConversationOwner",
    "DesktopIdentityRelaySessionOwner",
    "DesktopMemoryTriggerOwner",
    "DesktopPendingTurnOwner",
    "DesktopRuntimeConfigOwner",
    "DesktopScreenCaptureOwner",
    "ProductionDesktopAddonManagerBinding",
    "ProductionDesktopAssistantCommitBinding",
    "ProductionDesktopChatViewBinding",
    "ProductionDesktopCompatibilityBindings",
    "ProductionDesktopCompatibilityPorts",
    "ProductionDesktopConversationBinding",
    "ProductionDesktopConversationHistory",
    "ProductionDesktopIdentityRelaySessionBinding",
    "ProductionDesktopMemoryTriggerBinding",
    "ProductionDesktopNormalChatBlocked",
    "ProductionDesktopNormalChatTransactions",
    "ProductionDesktopPendingTurnBinding",
    "ProductionDesktopRelaySnapshots",
    "ProductionDesktopRuntimeConfigBinding",
    "ProductionDesktopScreenCaptureBinding",
]
