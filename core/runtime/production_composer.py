"""Explicit assembly of the production conversation and application owners."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from core.runtime.composition import RuntimeFoundation
from core.runtime.facade import (
    ApplicationActivity,
    ApplicationCallbackBinding,
    ApplicationDispatch,
    ApplicationManualInteraction,
)
from core.runtime.loop_control import ConversationLoopControlOwner
from core.runtime.production_addon_extensions import (
    ProductionAddonRuntimeExtensionOwners,
)
from core.runtime.production_application import ProductionApplicationBindings
from core.runtime.production_avatar import ProductionAvatarOwner
from core.runtime.production_bindings import ProductionRunBinding, ProductionStopBinding
from core.runtime.production_host import ProductionRunOrchestrator, ProductionStopOwner
from core.runtime.production_memory import ProductionMemoryOwner
from core.runtime.production_session import ProductionChatSessionOwner
from core.runtime.production_shutdown import ProductionShutdownOwner
from core.runtime.production_speech_backends import ProductionSpeechBackendOwner
from core.runtime.startup import ProductionStartupComposition, ProductionStartupOrchestrator


def _chat_message_deletion_busy(turns, playback, control):
    read = getattr(playback, 'activity_snapshot', playback.snapshot)
    state = read()
    return bool(turns.has_active_turns() or state.current or state.next
                or state.stopping or control.snapshot().audio_playing)


@dataclass(frozen=True, slots=True)
class ProductionCompositionRoots:
    """Factory-owned roots exposed to the one finite application composer."""

    foundation: RuntimeFoundation
    memory: ProductionMemoryOwner


@dataclass(frozen=True, slots=True)
class ProductionApplicationBindingEdges:
    """Platform edges that are not owned by the conversation graph."""

    dispatch: ApplicationDispatch | None = None
    activity: ApplicationActivity | None = None
    config_update: Callable[[str, object], object] | None = None
    bind_addon_manager_getter: ApplicationCallbackBinding | None = None
    bind_addon_event_publisher: ApplicationCallbackBinding | None = None
    submit_manual_interaction: ApplicationManualInteraction | None = None


@dataclass(frozen=True, slots=True)
class ProductionConversationOwnerGraph:
    """Concrete extracted owners shared by startup, facade, and addons."""

    startup: ProductionStartupComposition
    control: ConversationLoopControlOwner
    avatar: ProductionAvatarOwner
    speech_backends: ProductionSpeechBackendOwner
    chat_session: ProductionChatSessionOwner
    binding_edges: ProductionApplicationBindingEdges = field(
        default_factory=ProductionApplicationBindingEdges
    )
    conversation_actions: object | None = None


class ProductionConversationOwnerGraphFactory(Protocol):
    def __call__(
        self,
        roots: ProductionCompositionRoots,
    ) -> ProductionConversationOwnerGraph: ...


class ProductionCompletedAddonOwnersFactory(Protocol):
    """Build addon owners after their shared conversation owners exist."""

    def __call__(
        self,
        roots: ProductionCompositionRoots,
        graph: ProductionConversationOwnerGraph,
    ) -> ProductionAddonRuntimeExtensionOwners: ...


@dataclass(frozen=True, slots=True)
class ProductionApplicationCompositionState:
    """One completed application graph consumed atomically by the host factory."""

    addon_owners: ProductionAddonRuntimeExtensionOwners
    run_owner: ProductionRunOrchestrator
    stop_owner: ProductionStopOwner
    bindings: ProductionApplicationBindings
    retained_owners: tuple[object, ...]


class ProductionApplicationComposer(Protocol):
    def compose(
        self,
        roots: ProductionCompositionRoots,
    ) -> ProductionApplicationCompositionState: ...


class DefaultProductionApplicationComposer:
    """Compose shared owners first, then addon owners, then publish bindings."""

    __slots__ = ("_addon_factory", "_graph_factory")

    def __init__(
        self,
        *,
        graph_factory: ProductionConversationOwnerGraphFactory,
        addon_factory: ProductionCompletedAddonOwnersFactory,
    ) -> None:
        if not callable(graph_factory):
            raise TypeError("Production graph factory must be callable.")
        if not callable(addon_factory):
            raise TypeError("Production addon factory must be callable.")
        self._graph_factory = graph_factory
        self._addon_factory = addon_factory

    def compose(
        self,
        roots: ProductionCompositionRoots,
    ) -> ProductionApplicationCompositionState:
        if not isinstance(roots, ProductionCompositionRoots):
            raise TypeError("Production application composition requires named roots.")
        graph = self._graph_factory(roots)
        if not isinstance(graph, ProductionConversationOwnerGraph):
            raise TypeError(
                "Production graph factory must return ProductionConversationOwnerGraph."
            )

        run_owner = ProductionStartupOrchestrator(graph.startup)
        stop_owner = ProductionShutdownOwner(
            stop=graph.control.controls.stop,
            playback_stop=graph.control.controls.stop_playback,
            avatar=graph.avatar,
        )
        addon_owners = self._addon_factory(roots, graph)
        if not isinstance(addon_owners, ProductionAddonRuntimeExtensionOwners):
            raise TypeError(
                "Production addon factory must return "
                "ProductionAddonRuntimeExtensionOwners."
            )

        run_binding = ProductionRunBinding()
        stop_binding = ProductionStopBinding()
        stop_adapter = _UiStopOwner(stop_owner)
        bindings = _build_application_bindings(
            roots=roots,
            graph=graph,
            run_binding=run_binding,
            stop_binding=stop_binding,
        )

        # Publish callable bindings only after every owner has been created.
        run_binding.bind(run_owner)
        stop_binding.bind(stop_adapter)
        return ProductionApplicationCompositionState(
            addon_owners=addon_owners,
            run_owner=run_owner,
            stop_owner=stop_owner,
            bindings=bindings,
            retained_owners=(
                graph,
                run_binding,
                stop_binding,
                stop_adapter,
            ),
        )


class _UiStopOwner:
    __slots__ = ("_owner",)

    def __init__(self, owner: ProductionShutdownOwner) -> None:
        self._owner = owner

    def request_stop(self, *, engine_running: bool) -> None:
        self._owner.request_stop_for_ui(engine_running=bool(engine_running))


def _build_application_bindings(
    *,
    roots: ProductionCompositionRoots,
    graph: ProductionConversationOwnerGraph,
    run_binding: ProductionRunBinding,
    stop_binding: ProductionStopBinding,
) -> ProductionApplicationBindings:
    edges = graph.binding_edges
    avatar = graph.avatar
    speech = graph.speech_backends
    session = graph.chat_session
    memory = roots.memory

    def activity() -> tuple[bool, bool, bool]:
        snapshot = graph.control.snapshot()
        return (
            bool(snapshot.listening),
            bool(snapshot.microphone_active),
            bool(
                snapshot.manual_pause
                or snapshot.pause_after_chunk
                or snapshot.playback_paused
            ),
        )

    def replace_history(
        messages: list[Mapping[str, object]],
        allow_pending_loaded_user: bool,
        expected_history: list[Mapping[str, object]] | None,
        reconcile_long_term_memory_archive: bool,
    ) -> Mapping[str, object]:
        return session.replace_chat_conversation_history(
            messages,
            allow_pending_loaded_user=bool(allow_pending_loaded_user),
            expected_history=expected_history,
            reconcile_long_term_memory_archive=bool(
                reconcile_long_term_memory_archive
            ),
        )

    def edit_history(messages, revision, indices):
        repair = {}
        def reconcile(previous, replacement, source_indices):
            repair.update(memory.repair_mapped_history(previous, replacement, source_indices))
            return repair
        result = roots.foundation.conversation.edit_history_if_current(messages,
            expected_revision=revision, source_indices=indices, reconcile=reconcile)
        if result.accepted:
            try:
                memory.finish_history_repair(repair)
            except Exception as error:
                # The canonical edit already committed. Report a follow-up
                # failure without falsely claiming that its history was kept.
                memory.notify_updates({'history_repair': {**repair, 'phase': 'failed', 'error': str(error)}})
        return result

    def deletion_busy():
        # Admission stays stopped after shutdown; deletion needs live cleanup.
        return _chat_message_deletion_busy(roots.foundation.turns, roots.foundation.playback, graph.control)

    def delete_message(message_id, revision, generation, remove_memories):
        result = session.delete_chat_message(message_id, expected_revision=revision,
            expected_session=generation, remove_memories=remove_memories, is_busy=deletion_busy)
        if result.accepted:
            try:
                memory.finish_history_repair(dict(result.value.get('memory') or {}))
                memory.notify_updates({'long_term_memory_archive': True, 'continuity_memory': True})
            except Exception:
                # Notification failure cannot turn a committed deletion into a failure receipt.
                pass
        return result

    return ProductionApplicationBindings(
        dispatch=edges.dispatch,
        run=run_binding,
        request_stop=stop_binding,
        config_update=edges.config_update or roots.foundation.config.update,
        activity=edges.activity or activity,
        stt_backend_catalog=speech.stt_backend_catalog,
        stt_backend_reinitialize=speech.reinitialize_stt_backend,
        tts_backend_catalog=speech.tts_backend_catalog,
        tts_backend_reinitialize=speech.reinitialize_tts_backend,
        avatar_catalog=avatar.provider_catalog,
        avatar_select=avatar.select_provider,
        body_snapshot=lambda: avatar.body_snapshot().to_mapping(),
        body_set_live_sync=avatar.set_body_live_sync,
        body_select_emotion=avatar.select_body_emotion,
        body_update_pose=avatar.update_body_pose,
        body_update_profile=avatar.update_body_profile,
        body_update_hand_calibration=avatar.update_body_hand_calibration,
        bind_image_review=memory.bind_image_review,
        bind_addon_manager_getter=edges.bind_addon_manager_getter,
        bind_addon_event_publisher=edges.bind_addon_event_publisher,
        queue_typed_chat=session.queue_typed_chat_message,
        replace_chat_session_history=replace_history,
        delete_chat_message=delete_message,
        edit_chat_history=edit_history,
        conversation_actions=graph.conversation_actions,
        reset_chat_session=session.reset_session_state,
        export_chat_session=session.export_chat_session_state,
        import_chat_session=session.import_chat_session_state,
        submit_manual_interaction=edges.submit_manual_interaction,
        set_memory_context_path=memory.set_context_path,
        set_memory_identity=memory.set_identity,
        set_memory_embedding_baseline=memory.set_embedding_baseline,
        schedule_memory_context_flush=memory.schedule_context_flush,
        memory_work_context_is_current=memory.work_context_is_current,
        bind_memory_updates=memory.bind_updates,
        memory_continuity_snapshot=memory.continuity_snapshot,
        memory_status_view=memory.status_view,
        memory_embedding_status=memory.embedding_status,
        memory_embedding_blocked_event=memory.embedding_blocked_event,
        memory_embedding_models=memory.list_embedding_models,
        schedule_memory_embedding_rebuild=memory.schedule_embedding_rebuild,
        schedule_memory_archive_candidate=memory.schedule_archive_candidate,
        update_continuity_memory=memory.update_continuity,
        schedule_continuity_memory_batch=memory.schedule_continuity_batch,
        clear_continuity_memory=memory.clear_continuity,
        schedule_long_term_memory_extract=memory.schedule_extract,
        memory_archive_snapshot=memory.archive_snapshot,
        memory_export_default_path=memory.export_default_path,
        export_session_memory_report=memory.export_session_report,
        retrieve_long_term_memory=memory.retrieve,
    )


__all__ = [
    "DefaultProductionApplicationComposer",
    "ProductionApplicationBindingEdges",
    "ProductionApplicationComposer",
    "ProductionApplicationCompositionState",
    "ProductionCompletedAddonOwnersFactory",
    "ProductionCompositionRoots",
    "ProductionConversationOwnerGraph",
    "ProductionConversationOwnerGraphFactory",
]
