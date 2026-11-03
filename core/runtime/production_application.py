"""Explicit final composition root for one production application graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from core.runtime.addon_operations import build_addon_runtime_operations
from core.runtime.composition import RuntimeFoundation, finalize_runtime_context
from core.runtime.facade import (
    ApplicationActivity,
    ApplicationAvatarCatalog,
    ApplicationAvatarSelect,
    ApplicationBodyEmotionSelect,
    ApplicationBodyHandCalibrationUpdate,
    ApplicationBodyLiveSync,
    ApplicationBodyPoseUpdate,
    ApplicationBodyProfileUpdate,
    ApplicationBodySnapshot,
    ApplicationCallbackBinding,
    ApplicationChatHistoryReplace,
    ApplicationChatMessageDelete,
    ApplicationChatSessionExport,
    ApplicationChatSessionImport,
    ApplicationChatSessionReset,
    ApplicationChatTypedQueue,
    ApplicationConfigUpdate,
    ApplicationDispatch,
    ApplicationManualInteraction,
    ApplicationMemoryArchiveCandidate,
    ApplicationMemoryArchiveSnapshot,
    ApplicationMemoryContinuityBatch,
    ApplicationMemoryContinuityClear,
    ApplicationMemoryContinuitySnapshot,
    ApplicationMemoryContinuityUpdate,
    ApplicationMemoryContextPath,
    ApplicationMemoryEmbeddingBaseline,
    ApplicationMemoryEmbeddingBlockedEvent,
    ApplicationMemoryEmbeddingModels,
    ApplicationMemoryEmbeddingRebuild,
    ApplicationMemoryEmbeddingStatus,
    ApplicationMemoryExportDefaultPath,
    ApplicationMemoryExportReport,
    ApplicationMemoryExtract,
    ApplicationMemoryFlushSchedule,
    ApplicationMemoryIdentity,
    ApplicationMemoryRetrieve,
    ApplicationMemoryStatusView,
    ApplicationMemoryWorkCurrent,
    ApplicationRun,
    ApplicationSpeechBackendCatalog,
    ApplicationSpeechBackendReinitialize,
    ApplicationStopRequest,
)
from core.runtime.production_addon_extensions import (
    ProductionAddonRuntimeExtensionOwners,
    build_production_addon_runtime_extensions,
)
from core.runtime.production_host import (
    ProductionApplicationHost,
    ProductionRunOrchestrator,
    ProductionStopOwner,
)


@dataclass(frozen=True, slots=True)
class ProductionApplicationBindings:
    """Finite late-bound application ports installed into the public facade."""

    dispatch: ApplicationDispatch | None = None
    run: ApplicationRun | None = None
    request_stop: ApplicationStopRequest | None = None
    config_update: ApplicationConfigUpdate | None = None
    activity: ApplicationActivity | None = None
    stt_backend_catalog: ApplicationSpeechBackendCatalog | None = None
    stt_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None
    tts_backend_catalog: ApplicationSpeechBackendCatalog | None = None
    tts_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None
    avatar_catalog: ApplicationAvatarCatalog | None = None
    avatar_select: ApplicationAvatarSelect | None = None
    body_snapshot: ApplicationBodySnapshot | None = None
    body_set_live_sync: ApplicationBodyLiveSync | None = None
    body_select_emotion: ApplicationBodyEmotionSelect | None = None
    body_update_pose: ApplicationBodyPoseUpdate | None = None
    body_update_profile: ApplicationBodyProfileUpdate | None = None
    body_update_hand_calibration: ApplicationBodyHandCalibrationUpdate | None = None
    bind_image_review: ApplicationCallbackBinding | None = None
    bind_addon_manager_getter: ApplicationCallbackBinding | None = None
    bind_addon_event_publisher: ApplicationCallbackBinding | None = None
    queue_typed_chat: ApplicationChatTypedQueue | None = None
    replace_chat_session_history: ApplicationChatHistoryReplace | None = None
    edit_chat_history: Callable | None = None
    delete_chat_message: ApplicationChatMessageDelete | None = None
    conversation_actions: object | None = None
    reset_chat_session: ApplicationChatSessionReset | None = None
    export_chat_session: ApplicationChatSessionExport | None = None
    import_chat_session: ApplicationChatSessionImport | None = None
    submit_manual_interaction: ApplicationManualInteraction | None = None
    set_memory_context_path: ApplicationMemoryContextPath | None = None
    set_memory_identity: ApplicationMemoryIdentity | None = None
    set_memory_embedding_baseline: ApplicationMemoryEmbeddingBaseline | None = None
    schedule_memory_context_flush: ApplicationMemoryFlushSchedule | None = None
    memory_work_context_is_current: ApplicationMemoryWorkCurrent | None = None
    bind_memory_updates: ApplicationCallbackBinding | None = None
    memory_continuity_snapshot: ApplicationMemoryContinuitySnapshot | None = None
    memory_status_view: ApplicationMemoryStatusView | None = None
    memory_embedding_status: ApplicationMemoryEmbeddingStatus | None = None
    memory_embedding_blocked_event: ApplicationMemoryEmbeddingBlockedEvent | None = None
    memory_embedding_models: ApplicationMemoryEmbeddingModels | None = None
    schedule_memory_embedding_rebuild: ApplicationMemoryEmbeddingRebuild | None = None
    schedule_memory_archive_candidate: ApplicationMemoryArchiveCandidate | None = None
    update_continuity_memory: ApplicationMemoryContinuityUpdate | None = None
    schedule_continuity_memory_batch: ApplicationMemoryContinuityBatch | None = None
    clear_continuity_memory: ApplicationMemoryContinuityClear | None = None
    schedule_long_term_memory_extract: ApplicationMemoryExtract | None = None
    memory_archive_snapshot: ApplicationMemoryArchiveSnapshot | None = None
    memory_export_default_path: ApplicationMemoryExportDefaultPath | None = None
    export_session_memory_report: ApplicationMemoryExportReport | None = None
    retrieve_long_term_memory: ApplicationMemoryRetrieve | None = None


@dataclass(frozen=True, slots=True)
class ProductionApplicationDependencies:
    """Complete, named ownership input for one production application host."""

    foundation: RuntimeFoundation
    addon_owners: ProductionAddonRuntimeExtensionOwners
    run_owner: ProductionRunOrchestrator
    stop_owner: ProductionStopOwner
    bindings: ProductionApplicationBindings = field(
        default_factory=ProductionApplicationBindings
    )


def build_production_application(
    dependencies: ProductionApplicationDependencies,
) -> ProductionApplicationHost:
    """Finalize one context and bind its finite host and addon surfaces."""

    if not isinstance(dependencies, ProductionApplicationDependencies):
        raise TypeError(
            "Production application composition requires "
            "ProductionApplicationDependencies."
        )
    foundation = dependencies.foundation
    if not isinstance(foundation, RuntimeFoundation):
        raise TypeError("Production application requires RuntimeFoundation.")
    addon_owners = dependencies.addon_owners
    if not isinstance(addon_owners, ProductionAddonRuntimeExtensionOwners):
        raise TypeError(
            "Production application requires named addon extension owners."
        )
    bindings = dependencies.bindings
    if not isinstance(bindings, ProductionApplicationBindings):
        raise TypeError("Production application requires explicit bindings.")

    context = finalize_runtime_context(
        foundation,
        addon_chat_owner=addon_owners.chat_context_owner,
        addon_speech_owner=addon_owners.speech_owner,
        addon_push_to_talk_owner=addon_owners.push_to_talk_owner,
        addon_orb_owner=addon_owners.orb_owner,
        addon_audio_story_owner=addon_owners.audio_story_tts_owner,
        addon_avatar_resource_owner=addon_owners.avatar_resource_owner,
        addon_visual_request_owner=addon_owners.visual_request_owner,
        prompt_refinement_owner=addon_owners.prompt_refinement_owner,
        application_dispatch=bindings.dispatch,
        application_run=bindings.run,
        application_request_stop=bindings.request_stop,
        application_config_update=bindings.config_update,
        application_activity=bindings.activity,
        application_stt_backend_catalog=bindings.stt_backend_catalog,
        application_stt_backend_reinitialize=bindings.stt_backend_reinitialize,
        application_tts_backend_catalog=bindings.tts_backend_catalog,
        application_tts_backend_reinitialize=bindings.tts_backend_reinitialize,
        application_avatar_catalog=bindings.avatar_catalog,
        application_avatar_select=bindings.avatar_select,
        application_body_snapshot=bindings.body_snapshot,
        application_body_set_live_sync=bindings.body_set_live_sync,
        application_body_select_emotion=bindings.body_select_emotion,
        application_body_update_pose=bindings.body_update_pose,
        application_body_update_profile=bindings.body_update_profile,
        application_body_update_hand_calibration=bindings.body_update_hand_calibration,
        application_bind_image_review=bindings.bind_image_review,
        application_bind_addon_manager_getter=bindings.bind_addon_manager_getter,
        application_bind_addon_event_publisher=bindings.bind_addon_event_publisher,
        application_queue_typed_chat=bindings.queue_typed_chat,
        application_replace_chat_session_history=bindings.replace_chat_session_history,
        application_delete_chat_message=bindings.delete_chat_message,
        application_edit_chat_history=bindings.edit_chat_history,
        application_conversation_actions=bindings.conversation_actions,
        application_reset_chat_session=bindings.reset_chat_session,
        application_export_chat_session=bindings.export_chat_session,
        application_import_chat_session=bindings.import_chat_session,
        application_submit_manual_interaction=bindings.submit_manual_interaction,
        application_set_memory_context_path=bindings.set_memory_context_path,
        application_set_memory_identity=bindings.set_memory_identity,
        application_set_memory_embedding_baseline=bindings.set_memory_embedding_baseline,
        application_schedule_memory_context_flush=bindings.schedule_memory_context_flush,
        application_memory_work_context_is_current=bindings.memory_work_context_is_current,
        application_bind_memory_updates=bindings.bind_memory_updates,
        application_memory_continuity_snapshot=bindings.memory_continuity_snapshot,
        application_memory_status_view=bindings.memory_status_view,
        application_memory_embedding_status=bindings.memory_embedding_status,
        application_memory_embedding_blocked_event=bindings.memory_embedding_blocked_event,
        application_memory_embedding_models=bindings.memory_embedding_models,
        application_schedule_memory_embedding_rebuild=bindings.schedule_memory_embedding_rebuild,
        application_schedule_memory_archive_candidate=bindings.schedule_memory_archive_candidate,
        application_update_continuity_memory=bindings.update_continuity_memory,
        application_schedule_continuity_memory_batch=bindings.schedule_continuity_memory_batch,
        application_clear_continuity_memory=bindings.clear_continuity_memory,
        application_schedule_long_term_memory_extract=bindings.schedule_long_term_memory_extract,
        application_memory_archive_snapshot=bindings.memory_archive_snapshot,
        application_memory_export_default_path=bindings.memory_export_default_path,
        application_export_session_memory_report=bindings.export_session_memory_report,
        application_retrieve_long_term_memory=bindings.retrieve_long_term_memory,
    )
    extensions = build_production_addon_runtime_extensions(addon_owners)
    addon_operations = build_addon_runtime_operations(context, extensions)
    return ProductionApplicationHost(
        context=context,
        orchestrator=dependencies.run_owner,
        stop_owner=dependencies.stop_owner,
        addon_runtime_operations=addon_operations,
    )


__all__ = [
    "ProductionApplicationBindings",
    "ProductionApplicationDependencies",
    "build_production_application",
]
