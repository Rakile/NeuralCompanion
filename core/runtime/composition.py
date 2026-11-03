"""Deterministic construction and lifecycle entry points for the runtime graph."""

from __future__ import annotations
from core.runtime.runtime_use import RuntimeUseGate

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.runtime.addon_extensions import (
    AudioStoryTtsRuntimeExtensionOwner,
    AvatarResourceRuntimeExtensionOwner,
    ChatContextRuntimeExtensionOwner,
    OrbRuntimeExtensionOwner,
    PromptRefinementRuntimeExtensionOwner,
    PushToTalkRuntimeExtensionOwner,
    SpeechRuntimeExtensionOwner,
    VisualRequestRuntimeExtensionOwner,
)
from core.runtime.addons import AddonGateway
from core.runtime.avatar import AvatarService
from core.runtime.body_profile import BodyProfileService
from core.runtime.config import RuntimeConfigService
from core.runtime.config_effects import RuntimeConfigEffects
from core.runtime.context import RuntimeContext
from core.runtime.contracts import CommandResult
from core.runtime.controllers import ControllerSetupRegistry
from core.runtime.conversation import ConversationService
from core.runtime.events import RuntimeEventBus
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
    ApplicationConfigUpdate,
    ApplicationDispatch,
    ApplicationMemoryArchiveCandidate,
    ApplicationMemoryArchiveSnapshot,
    ApplicationMemoryContinuityBatch,
    ApplicationMemoryContinuityClear,
    ApplicationMemoryContinuitySnapshot,
    ApplicationMemoryContinuityUpdate,
    ApplicationMemoryEmbeddingBlockedEvent,
    ApplicationMemoryEmbeddingModels,
    ApplicationMemoryEmbeddingRebuild,
    ApplicationMemoryEmbeddingStatus,
    ApplicationMemoryExportDefaultPath,
    ApplicationMemoryExportReport,
    ApplicationMemoryExtract,
    ApplicationMemoryRetrieve,
    ApplicationMemoryStatusView,
    ApplicationRun,
    ApplicationSpeechBackendCatalog,
    ApplicationSpeechBackendReinitialize,
    ApplicationStopRequest,
    build_application_facade,
)
from core.runtime.identity_relay import (
    IdentityRelayArtifactCapabilities,
    IdentityRelayService,
)
from core.runtime.interaction import (
    InteractionCapabilities,
    InteractionCommand,
    InteractionService,
)
from core.runtime.lifecycle import RuntimeLifecycle, WorkerSupervisor
from core.runtime.memory import MemoryRecallCapabilities, MemoryService
from core.runtime.memory_admin import MemoryAdminService
from core.runtime.playback import (
    PlaybackService,
    ReplayPlaybackPipeline,
    ReplayPlaybackPipelineCapabilities,
)
from core.runtime.proactive import ProactiveCandidate, ProactiveService
from core.runtime.prompt_assembly import PromptAssemblyService
from core.runtime.providers import (
    ModelLoad,
    ModelPlaceholderCheck,
    ModelUnload,
    ProviderService,
)
from core.runtime.replay import ReplayService, VoiceResolver
from core.runtime.sensory import SensoryCapabilities, SensoryService
from core.runtime.session_resources import SessionResourceGuard
from core.runtime.speech_input import (
    SpeechInputCapabilities,
    SpeechInputService,
    SpeechInputTuning,
)
from core.runtime.speech_output import SpeechOutputCapabilities, SpeechOutputService
from core.runtime.turns import TurnCoordinator, TurnTerminal
from core.runtime.visual import VisualCapabilities, VisualResult, VisualService

if TYPE_CHECKING:
    from core.runtime_chat import ChatProviderRuntime


LifecycleCallback = Callable[[], object]
TurnInvalidationCallback = Callable[[TurnTerminal], None]
ConversationMemoryOperation = Callable[[object], object]
ConversationMemoryCompletion = Callable[[object, object], object]
ConversationMemoryUpdated = Callable[[object, object], None]
IdentityRelayTokenCounter = Callable[[object, object], int]
IdentityRelayProviderDispatch = Callable[[object, object, str], None]
IdentityRelayRuntimeEmbedding = Callable[..., object]
IdentityRelayRuntimeDeleteTransaction = Callable[[object, object], object]
IdentityRelayRuntimeDerivativePurge = Callable[[object], object]


@dataclass(frozen=True, slots=True)
class RuntimeFoundation:
    """Runtime-owned services constructed before UI/application bindings exist."""

    config: RuntimeConfigService
    config_effects: RuntimeConfigEffects
    lifecycle: RuntimeLifecycle
    workers: WorkerSupervisor
    controllers: ControllerSetupRegistry
    conversation: ConversationService
    session_guard: SessionResourceGuard
    speech_input: SpeechInputService
    speech_output: SpeechOutputService
    playback: PlaybackService
    avatar: AvatarService
    body_profile: BodyProfileService
    visual: VisualService
    sensory: SensoryService
    proactive: ProactiveService
    interaction: InteractionService
    replay: ReplayService
    addons: AddonGateway
    events: RuntimeEventBus
    providers: ProviderService
    prompt_assembly: PromptAssemblyService
    memory: MemoryService
    memory_admin: MemoryAdminService
    identity_relay: IdentityRelayService
    turns: TurnCoordinator
    runtime_use: RuntimeUseGate


class _NoopPlaybackDevice:
    def play(self, _chunk: object, _stop_event: object, _owner: object) -> None:
        return None

    def stop(self, _owner: object) -> None:
        return None


class _PlaybackLifecycleParticipant:
    name = "playback"

    def __init__(self, service: PlaybackService) -> None:
        self._service = service

    def start(self) -> CommandResult[None]:
        return self._service.start()

    def stop(self) -> CommandResult[None]:
        receipt = self._service.stop("runtime_shutdown")
        if receipt.failure is not None:
            return CommandResult(False, failure=receipt.failure)
        return CommandResult(True)


class _LegacyLifecycleParticipant:
    name = "legacy_engine_startup"

    def __init__(
        self,
        startup: LifecycleCallback | None,
        shutdown: LifecycleCallback | None,
    ) -> None:
        self._startup = startup
        self._shutdown = shutdown

    def start(self) -> CommandResult[None]:
        if self._startup is not None:
            self._startup()
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        if self._shutdown is not None:
            self._shutdown()
        return CommandResult(True)


class _ConfigEffectsLifecycleParticipant:
    name = "config_effects"

    def __init__(self, effects: RuntimeConfigEffects) -> None:
        self._effects = effects

    def start(self) -> CommandResult[None]:
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        self._effects.close()
        return CommandResult(True)

def compose_runtime_foundation(
    initial_config: Mapping[str, object],
    *,
    config_service: RuntimeConfigService | None = None,
    worker_supervisor: WorkerSupervisor | None = None,
    conversation_service: ConversationService | None = None,
    provider_service: ProviderService | None = None,
    session_resource_guard: SessionResourceGuard | None = None,
    memory_service: MemoryService | None = None,
    memory_admin_service: MemoryAdminService | None = None,
    identity_relay_service: IdentityRelayService | None = None,
    legacy_startup: LifecycleCallback | None = None,
    legacy_shutdown: LifecycleCallback | None = None,
    provider_runtime: ChatProviderRuntime | None = None,
    model_unload: ModelUnload | None = None,
    model_load: ModelLoad | None = None,
    is_model_placeholder: ModelPlaceholderCheck | None = None,
    speech_input_capabilities: SpeechInputCapabilities | None = None,
    speech_input_tuning: SpeechInputTuning | None = None,
    speech_input_logger: Callable[[str], None] | None = None,
    speech_output_capabilities: SpeechOutputCapabilities | None = None,
    playback_device: object | None = None,
    replay_playback_capabilities: ReplayPlaybackPipelineCapabilities | None = None,
    avatar_adapter: object | None = None,
    visual_capabilities: VisualCapabilities | None = None,
    visual_request_id_factory: Callable[[], str] | None = None,
    sensory_capabilities: SensoryCapabilities | None = None,
    sensory_registry: object | None = None,
    interaction_capabilities: InteractionCapabilities | None = None,
    interaction_queue_size: int = 32,
    replay_voice_resolver: VoiceResolver | None = None,
    replay_id_factory: Callable[[], str] | None = None,
    replay_trace: Callable[[str, Mapping[str, object]], object] | None = None,
    controller_setup_drain_timeout_seconds: float = 0.5,
    identity_relay_artifacts: IdentityRelayArtifactCapabilities | None = None,
    identity_relay_count_tokens: IdentityRelayTokenCounter | None = None,
    identity_relay_provider_dispatch: IdentityRelayProviderDispatch | None = None,
    identity_relay_logger: Callable[[str], None] | None = None,
    identity_relay_runtime_embedding: IdentityRelayRuntimeEmbedding | None = None,
    identity_relay_runtime_delete_transaction: IdentityRelayRuntimeDeleteTransaction
    | None = None,
    identity_relay_runtime_derivative_purge: IdentityRelayRuntimeDerivativePurge
    | None = None,
    turn_invalidation: TurnInvalidationCallback | None = None,
    memory_recall_capabilities: MemoryRecallCapabilities | None = None,
    memory_archive_embed_chunk: Callable[[object, object], object] | None = None,
    memory_archive_embedding_write_blocked: Callable[[Mapping[str, object]], bool] | None = None,
    memory_archive_embedding_blocked: Callable[[object], None] | None = None,
    memory_logger: Callable[[str], None] | None = None,
    conversation_memory_operation: ConversationMemoryOperation | None = None,
    conversation_memory_complete: ConversationMemoryCompletion | None = None,
    conversation_memory_updated: ConversationMemoryUpdated | None = None,
    runtime_dir: str | Path | None = None,
    body_profile: Mapping[str, object] | None = None,
    body_state: Mapping[str, object] | None = None,
    body_hand_calibration: Mapping[str, object] | None = None,
    body_edit_emotion: object = "neutral",
    body_force_edit_mode: bool = True,
) -> RuntimeFoundation:
    """Construct runtime-owned services without requiring application bindings."""

    config = config_service or RuntimeConfigService(initial_config)
    config_effects = RuntimeConfigEffects(config)
    workers = worker_supervisor or WorkerSupervisor()
    controllers = ControllerSetupRegistry(
        drain_timeout_seconds=controller_setup_drain_timeout_seconds
    )
    conversation = conversation_service or ConversationService()
    turns_ref: list[TurnCoordinator] = []
    replay_ref: list[ReplayService] = []
    events = RuntimeEventBus()
    if provider_service is None:
        if provider_runtime is None:
            from core.runtime_chat import ChatProviderRuntime

            owned_provider_runtime = ChatProviderRuntime(config.snapshot)
        else:
            owned_provider_runtime = provider_runtime
        providers = ProviderService(
            owned_provider_runtime,
            workers=workers,
            worker_lease=conversation.session_lease,
            model_unload=model_unload,
            model_load=model_load,
            is_model_placeholder=is_model_placeholder,
        )
    else:
        providers = provider_service

    def speech_lease_is_current(lease) -> bool:
        if lease.turn_id is not None:
            if conversation.turn_lease_is_current(lease):
                return True
            if replay_ref and replay_ref[0].lease_is_current(lease):
                return True
            return bool(
                controllers.registrations(binding=lease)
                and conversation.session_lease_is_current(lease)
            )
        return conversation.session_lease_is_current(lease)

    def visual_lease_is_current(lease) -> bool:
        if lease.turn_id is not None and turns_ref:
            return turns_ref[0].committed_effect_lease_is_valid(lease)
        if lease.turn_id is not None:
            return conversation.turn_lease_is_current(lease)
        return conversation.session_lease_is_current(lease)

    speech_input = SpeechInputService(
        workers=workers,
        config_snapshot=config.snapshot,
        lease_factory=conversation.session_lease,
        lease_is_current=speech_lease_is_current,
        capabilities=speech_input_capabilities,
        tuning=speech_input_tuning,
        logger=speech_input_logger,
    )
    avatar = AvatarService(
        adapter=avatar_adapter,
        lease_is_current=speech_lease_is_current,
    )
    speech_output = SpeechOutputService(
        workers=workers,
        capabilities=speech_output_capabilities,
        prepared_observer=avatar.on_audio_prepared,
        admit_prepared_effect=conversation.admit_session_effect,
        release_prepared_effect=conversation.release_session_effect,
    )
    interaction = InteractionService(
        max_queue_size=interaction_queue_size,
        capabilities=interaction_capabilities,
        config_snapshot=config.snapshot,
    )
    playback = PlaybackService(
        device=playback_device or _NoopPlaybackDevice(),
        lease_is_current=speech_lease_is_current,
        observer=avatar,
    )
    replay_playback_pipeline = (
        ReplayPlaybackPipeline(
            workers=workers,
            capabilities=replay_playback_capabilities,
        )
        if replay_playback_capabilities is not None
        else None
    )
    replay = ReplayService(
        conversation=conversation,
        config=config,
        speech_output=speech_output,
        playback=playback,
        controllers=controllers,
        playback_pipeline=replay_playback_pipeline,
        resolve_voice=replay_voice_resolver,
        replay_id_factory=replay_id_factory,
        trace=(
            replay_playback_capabilities.trace
            if replay_playback_capabilities is not None
            else replay_trace
        ),
    )
    replay_ref.append(replay)
    addons = AddonGateway()
    session_guard = session_resource_guard or SessionResourceGuard(conversation)

    def commit_visual_completion(lease, effect) -> CommandResult[VisualResult]:
        return session_guard.link_visual_result(
            lease,
            lambda: effect() if visual_lease_is_current(lease) else _raise_stale_visual(),
        )

    visual = VisualService(
        workers=workers,
        lease_is_current=visual_lease_is_current,
        capabilities=visual_capabilities,
        request_id_factory=visual_request_id_factory,
        commit_completion=commit_visual_completion,
    )
    memory = memory_service or MemoryService(
        workers=workers,
        session_guard=session_guard,
        session_lease=conversation.session_lease,
        session_lease_is_current=conversation.session_lease_is_current,
        config_snapshot=config.snapshot,
        recall_capabilities=memory_recall_capabilities,
        archive_embed_chunk=memory_archive_embed_chunk,
        archive_embedding_write_blocked=memory_archive_embedding_write_blocked,
        archive_embedding_blocked=memory_archive_embedding_blocked,
        logger=memory_logger,
        conversation_operation=conversation_memory_operation,
        conversation_complete=conversation_memory_complete,
        conversation_updated=conversation_memory_updated,
    )
    memory_admin = memory_admin_service or MemoryAdminService(
        memory_service=memory,
        session_guard=session_guard,
        runtime_dir=(Path(runtime_dir) if runtime_dir is not None else Path.cwd() / "runtime"),
        baseline_writer=lambda model, context_length: config.update_many(
            {
                "long_term_memory_embedding_session_model": str(model or ""),
                "long_term_memory_embedding_session_context": int(context_length),
            }
        ),
        format_turn_timestamp=lambda turn: str(turn.get("created_at") or "unknown"),
        logger=memory_logger,
    )
    body_profile_owner = BodyProfileService(
        profile=body_profile or {},
        state=body_state or {},
        hand_calibration=body_hand_calibration or {},
        edit_emotion=body_edit_emotion,
        force_edit_mode=body_force_edit_mode,
    )
    sensory = SensoryService(
        workers=workers,
        providers=providers,
        config_snapshot=config.snapshot,
        lease_factory=conversation.session_lease,
        lease_is_current=conversation.session_lease_is_current,
        registry=sensory_registry,
        capabilities=sensory_capabilities,
        admit_effect=conversation.admit_session_effect,
        release_effect=conversation.release_session_effect,
    )

    def publish_proactive_due(candidate: ProactiveCandidate) -> None:
        submitted = interaction.submit(
            InteractionCommand(
                candidate.action,
                payload={"candidate_id": candidate.candidate_id},
                source="proactive",
            )
        )
        if not submitted.accepted:
            failure = submitted.failure
            raise RuntimeError(
                failure.message
                if failure is not None
                else "The proactive interaction command was rejected."
            )

    proactive = ProactiveService(
        workers=workers,
        turns=None,
        lease_factory=conversation.session_lease,
        lease_is_current=conversation.session_lease_is_current,
        on_due=publish_proactive_due,
        admit_effect=conversation.admit_session_effect,
        release_effect=conversation.release_session_effect,
    )
    lifecycle = RuntimeLifecycle(
        (
            _LegacyLifecycleParticipant(legacy_startup, legacy_shutdown),
            _ConfigEffectsLifecycleParticipant(config_effects),
            speech_input,
            speech_output,
            avatar,
            _PlaybackLifecycleParticipant(playback),
            visual,
            memory,
            memory_admin,
            interaction,
            proactive,
            sensory,
            replay,
        ),
        supervisor=workers,
        run_generation=conversation,
    )
    prompt_assembly = PromptAssemblyService()
    identity_relay = identity_relay_service or IdentityRelayService(
        providers=providers,
        workers=workers,
        artifacts=identity_relay_artifacts,
        count_tokens=identity_relay_count_tokens,
        provider_dispatch=identity_relay_provider_dispatch,
        logger=identity_relay_logger,
        runtime_embedding=identity_relay_runtime_embedding,
        runtime_delete_transaction=identity_relay_runtime_delete_transaction,
        runtime_derivative_purge=identity_relay_runtime_derivative_purge,
    )

    def pre_invalidate_turn(terminal) -> CommandResult[object]:
        reason = str(terminal.reason or terminal.status.value)
        invalidated = controllers.invalidate_binding(
            terminal.lease,
            reason,
            after_seal=lambda: playback.cancel_lease(terminal.lease, reason),
        )
        if not invalidated.accepted:
            return CommandResult(False, failure=invalidated.failure)
        return CommandResult(
            invalidated.accepted,
            invalidated.value,
            invalidated.failure,
        )

    turns = TurnCoordinator(
        config=config,
        conversation=conversation,
        providers=providers,
        identity_relay=identity_relay,
        runtime=lifecycle,
        on_invalidate=turn_invalidation,
        pre_invalidation_guard=pre_invalidate_turn,
        persona_root=Path(runtime_dir).parent if runtime_dir is not None else None,
    )

    def invalidate_session_controller_scope(reason: str) -> CommandResult[object]:
        resolved_reason = str(reason or "session_transition")
        invalidated = controllers.invalidate_binding(
            conversation.session_lease(),
            resolved_reason,
            include_descendants=True,
            after_seal=lambda: playback.interrupt(resolved_reason),
        )
        if not invalidated.accepted:
            return CommandResult(False, failure=invalidated.failure)
        turns_invalidated = turns.invalidate_all(resolved_reason)
        if not turns_invalidated.accepted:
            return CommandResult(False, failure=turns_invalidated.failure)
        return CommandResult(
            invalidated.accepted,
            invalidated.value,
            invalidated.failure,
        )

    conversation.set_transition_invalidator(invalidate_session_controller_scope)
    turns_ref.append(turns)
    proactive.set_turns(turns)
    return RuntimeFoundation(
        config=config,
        config_effects=config_effects,
        lifecycle=lifecycle,
        workers=workers,
        controllers=controllers,
        conversation=conversation,
        session_guard=session_guard,
        speech_input=speech_input,
        speech_output=speech_output,
        playback=playback,
        avatar=avatar,
        body_profile=body_profile_owner,
        visual=visual,
        sensory=sensory,
        proactive=proactive,
        interaction=interaction,
        replay=replay,
        addons=addons,
        events=events,
        providers=providers,
        prompt_assembly=prompt_assembly,
        memory=memory,
        memory_admin=memory_admin,
        identity_relay=identity_relay,
        turns=turns,
        runtime_use=RuntimeUseGate(),
    )


def finalize_runtime_context(
    foundation: RuntimeFoundation,
    *,
    addon_chat_owner: ChatContextRuntimeExtensionOwner | None = None,
    addon_speech_owner: SpeechRuntimeExtensionOwner | None = None,
    addon_push_to_talk_owner: PushToTalkRuntimeExtensionOwner | None = None,
    addon_orb_owner: OrbRuntimeExtensionOwner | None = None,
    addon_audio_story_owner: AudioStoryTtsRuntimeExtensionOwner | None = None,
    addon_avatar_resource_owner: AvatarResourceRuntimeExtensionOwner | None = None,
    addon_visual_request_owner: VisualRequestRuntimeExtensionOwner | None = None,
    prompt_refinement_owner: PromptRefinementRuntimeExtensionOwner | None = None,
    application_dispatch: ApplicationDispatch | None = None,
    application_run: ApplicationRun | None = None,
    application_request_stop: ApplicationStopRequest | None = None,
    application_config_update: ApplicationConfigUpdate | None = None,
    application_activity: ApplicationActivity | None = None,
    application_stt_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_stt_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_tts_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_tts_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_avatar_catalog: ApplicationAvatarCatalog | None = None,
    application_avatar_select: ApplicationAvatarSelect | None = None,
    application_body_snapshot: ApplicationBodySnapshot | None = None,
    application_body_set_live_sync: ApplicationBodyLiveSync | None = None,
    application_body_select_emotion: ApplicationBodyEmotionSelect | None = None,
    application_body_update_pose: ApplicationBodyPoseUpdate | None = None,
    application_body_update_profile: ApplicationBodyProfileUpdate | None = None,
    application_body_update_hand_calibration: ApplicationBodyHandCalibrationUpdate | None = None,
    application_bind_image_review: ApplicationCallbackBinding | None = None,
    application_bind_addon_manager_getter: ApplicationCallbackBinding | None = None,
    application_bind_addon_event_publisher: ApplicationCallbackBinding | None = None,
    application_queue_typed_chat: Callable[[str, str | None, Mapping[str, object]], Mapping[str, object]] | None = None,
    application_replace_chat_session_history: Callable[[list[Mapping[str, object]], bool, list[Mapping[str, object]] | None, bool], Mapping[str, object]] | None = None,
    application_delete_chat_message: Callable | None = None,
    application_edit_chat_history: Callable | None = None,
    application_conversation_actions=None,
    application_reset_chat_session: Callable[[], object] | None = None,
    application_export_chat_session: Callable[[], Mapping[str, object]] | None = None,
    application_import_chat_session: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    application_submit_manual_interaction: Callable[[str], object] | None = None,
    application_set_memory_context_path: Callable[[str], Mapping[str, object]] | None = None,
    application_set_memory_identity: Callable[[str], str] | None = None,
    application_set_memory_embedding_baseline: Callable[[str | None, int | None], object] | None = None,
    application_schedule_memory_context_flush: Callable[[list[Mapping[str, object]], Callable[[object, object, object], object]], object] | None = None,
    application_memory_work_context_is_current: Callable[[object], bool] | None = None,
    application_bind_memory_updates: ApplicationCallbackBinding | None = None,
    application_memory_continuity_snapshot: ApplicationMemoryContinuitySnapshot | None = None,
    application_memory_status_view: ApplicationMemoryStatusView | None = None,
    application_memory_embedding_status: ApplicationMemoryEmbeddingStatus | None = None,
    application_memory_embedding_blocked_event: ApplicationMemoryEmbeddingBlockedEvent | None = None,
    application_memory_embedding_models: ApplicationMemoryEmbeddingModels | None = None,
    application_schedule_memory_embedding_rebuild: ApplicationMemoryEmbeddingRebuild | None = None,
    application_schedule_memory_archive_candidate: ApplicationMemoryArchiveCandidate | None = None,
    application_update_continuity_memory: ApplicationMemoryContinuityUpdate | None = None,
    application_schedule_continuity_memory_batch: ApplicationMemoryContinuityBatch | None = None,
    application_clear_continuity_memory: ApplicationMemoryContinuityClear | None = None,
    application_schedule_long_term_memory_extract: ApplicationMemoryExtract | None = None,
    application_memory_archive_snapshot: ApplicationMemoryArchiveSnapshot | None = None,
    application_memory_export_default_path: ApplicationMemoryExportDefaultPath | None = None,
    application_export_session_memory_report: ApplicationMemoryExportReport | None = None,
    application_retrieve_long_term_memory: ApplicationMemoryRetrieve | None = None,
) -> RuntimeContext:
    """Bind application and addon owners to a completed runtime foundation."""

    config = foundation.config
    config_effects = foundation.config_effects
    lifecycle = foundation.lifecycle
    conversation = foundation.conversation
    turns = foundation.turns
    providers = foundation.providers
    speech_input = foundation.speech_input
    speech_output = foundation.speech_output
    playback = foundation.playback
    replay = foundation.replay
    avatar = foundation.avatar
    visual = foundation.visual
    memory = foundation.memory
    memory_admin = foundation.memory_admin
    body_profile_owner = foundation.body_profile
    sensory = foundation.sensory
    interaction = foundation.interaction
    addons = foundation.addons
    prompt_assembly = foundation.prompt_assembly
    events = foundation.events
    facade = build_application_facade(
        runtime_use=foundation.runtime_use,
        lifecycle=lifecycle,
        config=config,
        conversation=conversation,
        turns=turns,
        providers=providers,
        speech_input=speech_input,
        speech_output=speech_output,
        playback=playback,
        replay=replay,
        avatar=avatar,
        visual=visual,
        memory=memory,
        memory_admin=memory_admin,
        config_effects=config_effects,
        body_profile=body_profile_owner,
        sensory=sensory,
        interaction=interaction,
        identity_relay=foundation.identity_relay,
        addons=addons,
        prompt_assembly=prompt_assembly,
        events=events,
        dispatch=application_dispatch,
        application_run=application_run,
        application_request_stop=application_request_stop,
        application_config_update=application_config_update,
        application_activity=application_activity,
        application_stt_backend_catalog=application_stt_backend_catalog,
        application_stt_backend_reinitialize=application_stt_backend_reinitialize,
        application_tts_backend_catalog=application_tts_backend_catalog,
        application_tts_backend_reinitialize=application_tts_backend_reinitialize,
        application_avatar_catalog=application_avatar_catalog,
        application_avatar_select=application_avatar_select,
        application_body_snapshot=application_body_snapshot,
        application_body_set_live_sync=application_body_set_live_sync,
        application_body_select_emotion=application_body_select_emotion,
        application_body_update_pose=application_body_update_pose,
        application_body_update_profile=application_body_update_profile,
        application_body_update_hand_calibration=application_body_update_hand_calibration,
        application_bind_image_review=application_bind_image_review,
        application_bind_addon_manager_getter=application_bind_addon_manager_getter,
        application_bind_addon_event_publisher=application_bind_addon_event_publisher,
        application_queue_typed_chat=application_queue_typed_chat,
        application_replace_chat_session_history=application_replace_chat_session_history,
        application_delete_chat_message=application_delete_chat_message,
        application_edit_chat_history=application_edit_chat_history,
        application_conversation_actions=application_conversation_actions,
        application_reset_chat_session=application_reset_chat_session,
        application_export_chat_session=application_export_chat_session,
        application_import_chat_session=application_import_chat_session,
        application_submit_manual_interaction=application_submit_manual_interaction,
        application_set_memory_context_path=application_set_memory_context_path,
        application_set_memory_identity=application_set_memory_identity,
        application_set_memory_embedding_baseline=application_set_memory_embedding_baseline,
        application_schedule_memory_context_flush=application_schedule_memory_context_flush,
        application_memory_work_context_is_current=application_memory_work_context_is_current,
        application_bind_memory_updates=application_bind_memory_updates,
        application_memory_continuity_snapshot=application_memory_continuity_snapshot,
        application_memory_status_view=application_memory_status_view,
        application_memory_embedding_status=application_memory_embedding_status,
        application_memory_embedding_blocked_event=application_memory_embedding_blocked_event,
        application_memory_embedding_models=application_memory_embedding_models,
        application_schedule_memory_embedding_rebuild=application_schedule_memory_embedding_rebuild,
        application_schedule_memory_archive_candidate=application_schedule_memory_archive_candidate,
        application_update_continuity_memory=application_update_continuity_memory,
        application_schedule_continuity_memory_batch=application_schedule_continuity_memory_batch,
        application_clear_continuity_memory=application_clear_continuity_memory,
        application_schedule_long_term_memory_extract=application_schedule_long_term_memory_extract,
        application_memory_archive_snapshot=application_memory_archive_snapshot,
        application_memory_export_default_path=application_memory_export_default_path,
        application_export_session_memory_report=application_export_session_memory_report,
        application_retrieve_long_term_memory=application_retrieve_long_term_memory,
        addon_chat_owner=addon_chat_owner,
        addon_speech_owner=addon_speech_owner,
        addon_push_to_talk_owner=addon_push_to_talk_owner,
        addon_orb_owner=addon_orb_owner,
        addon_audio_story_owner=addon_audio_story_owner,
        addon_avatar_resource_owner=addon_avatar_resource_owner,
        addon_visual_request_owner=addon_visual_request_owner,
        prompt_refinement_owner=prompt_refinement_owner,
    )
    return RuntimeContext(
        facade=facade,
        config=foundation.config,
        config_effects=foundation.config_effects,
        lifecycle=foundation.lifecycle,
        workers=foundation.workers,
        controllers=foundation.controllers,
        conversation=foundation.conversation,
        speech_input=foundation.speech_input,
        speech_output=foundation.speech_output,
        playback=foundation.playback,
        avatar=foundation.avatar,
        body_profile=foundation.body_profile,
        visual=foundation.visual,
        sensory=foundation.sensory,
        proactive=foundation.proactive,
        interaction=foundation.interaction,
        replay=foundation.replay,
        addons=foundation.addons,
        events=foundation.events,
        providers=foundation.providers,
        prompt_assembly=foundation.prompt_assembly,
        memory=foundation.memory,
        memory_admin=foundation.memory_admin,
        identity_relay=foundation.identity_relay,
        turns=foundation.turns,
    )


def compose_runtime(
    initial_config: Mapping[str, object],
    *,
    config_service: RuntimeConfigService | None = None,
    worker_supervisor: WorkerSupervisor | None = None,
    conversation_service: ConversationService | None = None,
    provider_service: ProviderService | None = None,
    session_resource_guard: SessionResourceGuard | None = None,
    memory_service: MemoryService | None = None,
    memory_admin_service: MemoryAdminService | None = None,
    identity_relay_service: IdentityRelayService | None = None,
    addon_chat_owner: ChatContextRuntimeExtensionOwner | None = None,
    addon_speech_owner: SpeechRuntimeExtensionOwner | None = None,
    addon_push_to_talk_owner: PushToTalkRuntimeExtensionOwner | None = None,
    addon_orb_owner: OrbRuntimeExtensionOwner | None = None,
    addon_audio_story_owner: AudioStoryTtsRuntimeExtensionOwner | None = None,
    addon_avatar_resource_owner: AvatarResourceRuntimeExtensionOwner | None = None,
    addon_visual_request_owner: VisualRequestRuntimeExtensionOwner | None = None,
    prompt_refinement_owner: PromptRefinementRuntimeExtensionOwner | None = None,
    legacy_startup: LifecycleCallback | None = None,
    legacy_shutdown: LifecycleCallback | None = None,
    provider_runtime: ChatProviderRuntime | None = None,
    model_unload: ModelUnload | None = None,
    model_load: ModelLoad | None = None,
    is_model_placeholder: ModelPlaceholderCheck | None = None,
    speech_input_capabilities: SpeechInputCapabilities | None = None,
    speech_input_tuning: SpeechInputTuning | None = None,
    speech_input_logger: Callable[[str], None] | None = None,
    speech_output_capabilities: SpeechOutputCapabilities | None = None,
    playback_device: object | None = None,
    replay_playback_capabilities: ReplayPlaybackPipelineCapabilities | None = None,
    avatar_adapter: object | None = None,
    visual_capabilities: VisualCapabilities | None = None,
    visual_request_id_factory: Callable[[], str] | None = None,
    sensory_capabilities: SensoryCapabilities | None = None,
    sensory_registry: object | None = None,
    interaction_capabilities: InteractionCapabilities | None = None,
    interaction_queue_size: int = 32,
    replay_voice_resolver: VoiceResolver | None = None,
    replay_id_factory: Callable[[], str] | None = None,
    replay_trace: Callable[[str, Mapping[str, object]], object] | None = None,
    controller_setup_drain_timeout_seconds: float = 0.5,
    identity_relay_artifacts: IdentityRelayArtifactCapabilities | None = None,
    identity_relay_count_tokens: IdentityRelayTokenCounter | None = None,
    identity_relay_provider_dispatch: IdentityRelayProviderDispatch | None = None,
    identity_relay_logger: Callable[[str], None] | None = None,
    identity_relay_runtime_embedding: IdentityRelayRuntimeEmbedding | None = None,
    identity_relay_runtime_delete_transaction: IdentityRelayRuntimeDeleteTransaction
    | None = None,
    identity_relay_runtime_derivative_purge: IdentityRelayRuntimeDerivativePurge
    | None = None,
    turn_invalidation: TurnInvalidationCallback | None = None,
    memory_recall_capabilities: MemoryRecallCapabilities | None = None,
    memory_archive_embed_chunk: Callable[[object, object], object] | None = None,
    memory_archive_embedding_write_blocked: Callable[[Mapping[str, object]], bool] | None = None,
    memory_archive_embedding_blocked: Callable[[object], None] | None = None,
    memory_logger: Callable[[str], None] | None = None,
    conversation_memory_operation: ConversationMemoryOperation | None = None,
    conversation_memory_complete: ConversationMemoryCompletion | None = None,
    conversation_memory_updated: ConversationMemoryUpdated | None = None,
    runtime_dir: str | Path | None = None,
    body_profile: Mapping[str, object] | None = None,
    body_state: Mapping[str, object] | None = None,
    body_hand_calibration: Mapping[str, object] | None = None,
    body_edit_emotion: object = "neutral",
    body_force_edit_mode: bool = True,
    application_dispatch: ApplicationDispatch | None = None,
    application_run: ApplicationRun | None = None,
    application_request_stop: ApplicationStopRequest | None = None,
    application_config_update: ApplicationConfigUpdate | None = None,
    application_activity: ApplicationActivity | None = None,
    application_stt_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_stt_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_tts_backend_catalog: ApplicationSpeechBackendCatalog | None = None,
    application_tts_backend_reinitialize: ApplicationSpeechBackendReinitialize | None = None,
    application_avatar_catalog: ApplicationAvatarCatalog | None = None,
    application_avatar_select: ApplicationAvatarSelect | None = None,
    application_body_snapshot: ApplicationBodySnapshot | None = None,
    application_body_set_live_sync: ApplicationBodyLiveSync | None = None,
    application_body_select_emotion: ApplicationBodyEmotionSelect | None = None,
    application_body_update_pose: ApplicationBodyPoseUpdate | None = None,
    application_body_update_profile: ApplicationBodyProfileUpdate | None = None,
    application_body_update_hand_calibration: ApplicationBodyHandCalibrationUpdate | None = None,
    application_bind_image_review: ApplicationCallbackBinding | None = None,
    application_bind_addon_manager_getter: ApplicationCallbackBinding | None = None,
    application_bind_addon_event_publisher: ApplicationCallbackBinding | None = None,
    application_queue_typed_chat: Callable[[str, str | None, Mapping[str, object]], Mapping[str, object]] | None = None,
    application_replace_chat_session_history: Callable[[list[Mapping[str, object]], bool, list[Mapping[str, object]] | None, bool], Mapping[str, object]] | None = None,
    application_delete_chat_message: Callable | None = None,
    application_edit_chat_history: Callable | None = None,
    application_conversation_actions=None,
    application_reset_chat_session: Callable[[], object] | None = None,
    application_export_chat_session: Callable[[], Mapping[str, object]] | None = None,
    application_import_chat_session: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    application_submit_manual_interaction: Callable[[str], object] | None = None,
    application_set_memory_context_path: Callable[[str], Mapping[str, object]] | None = None,
    application_set_memory_identity: Callable[[str], str] | None = None,
    application_set_memory_embedding_baseline: Callable[[str | None, int | None], object] | None = None,
    application_schedule_memory_context_flush: Callable[[list[Mapping[str, object]], Callable[[object, object, object], object]], object] | None = None,
    application_memory_work_context_is_current: Callable[[object], bool] | None = None,
    application_bind_memory_updates: ApplicationCallbackBinding | None = None,
    application_memory_continuity_snapshot: ApplicationMemoryContinuitySnapshot | None = None,
    application_memory_status_view: ApplicationMemoryStatusView | None = None,
    application_memory_embedding_status: ApplicationMemoryEmbeddingStatus | None = None,
    application_memory_embedding_blocked_event: ApplicationMemoryEmbeddingBlockedEvent | None = None,
    application_memory_embedding_models: ApplicationMemoryEmbeddingModels | None = None,
    application_schedule_memory_embedding_rebuild: ApplicationMemoryEmbeddingRebuild | None = None,
    application_schedule_memory_archive_candidate: ApplicationMemoryArchiveCandidate | None = None,
    application_update_continuity_memory: ApplicationMemoryContinuityUpdate | None = None,
    application_schedule_continuity_memory_batch: ApplicationMemoryContinuityBatch | None = None,
    application_clear_continuity_memory: ApplicationMemoryContinuityClear | None = None,
    application_schedule_long_term_memory_extract: ApplicationMemoryExtract | None = None,
    application_memory_archive_snapshot: ApplicationMemoryArchiveSnapshot | None = None,
    application_memory_export_default_path: ApplicationMemoryExportDefaultPath | None = None,
    application_export_session_memory_report: ApplicationMemoryExportReport | None = None,
    application_retrieve_long_term_memory: ApplicationMemoryRetrieve | None = None,
) -> RuntimeContext:
    """Backward-compatible one-step wrapper around two-phase composition."""

    foundation = compose_runtime_foundation(
        initial_config,
        config_service=config_service,
        worker_supervisor=worker_supervisor,
        conversation_service=conversation_service,
        provider_service=provider_service,
        session_resource_guard=session_resource_guard,
        memory_service=memory_service,
        memory_admin_service=memory_admin_service,
        identity_relay_service=identity_relay_service,
        legacy_startup=legacy_startup,
        legacy_shutdown=legacy_shutdown,
        provider_runtime=provider_runtime,
        model_unload=model_unload,
        model_load=model_load,
        is_model_placeholder=is_model_placeholder,
        speech_input_capabilities=speech_input_capabilities,
        speech_input_tuning=speech_input_tuning,
        speech_input_logger=speech_input_logger,
        speech_output_capabilities=speech_output_capabilities,
        playback_device=playback_device,
        replay_playback_capabilities=replay_playback_capabilities,
        avatar_adapter=avatar_adapter,
        visual_capabilities=visual_capabilities,
        visual_request_id_factory=visual_request_id_factory,
        sensory_capabilities=sensory_capabilities,
        sensory_registry=sensory_registry,
        interaction_capabilities=interaction_capabilities,
        interaction_queue_size=interaction_queue_size,
        replay_voice_resolver=replay_voice_resolver,
        replay_id_factory=replay_id_factory,
        replay_trace=replay_trace,
        controller_setup_drain_timeout_seconds=controller_setup_drain_timeout_seconds,
        identity_relay_artifacts=identity_relay_artifacts,
        identity_relay_count_tokens=identity_relay_count_tokens,
        identity_relay_provider_dispatch=identity_relay_provider_dispatch,
        identity_relay_logger=identity_relay_logger,
        identity_relay_runtime_embedding=identity_relay_runtime_embedding,
        identity_relay_runtime_delete_transaction=identity_relay_runtime_delete_transaction,
        identity_relay_runtime_derivative_purge=identity_relay_runtime_derivative_purge,
        turn_invalidation=turn_invalidation,
        memory_recall_capabilities=memory_recall_capabilities,
        memory_archive_embed_chunk=memory_archive_embed_chunk,
        memory_archive_embedding_write_blocked=memory_archive_embedding_write_blocked,
        memory_archive_embedding_blocked=memory_archive_embedding_blocked,
        memory_logger=memory_logger,
        conversation_memory_operation=conversation_memory_operation,
        conversation_memory_complete=conversation_memory_complete,
        conversation_memory_updated=conversation_memory_updated,
        runtime_dir=runtime_dir,
        body_profile=body_profile,
        body_state=body_state,
        body_hand_calibration=body_hand_calibration,
        body_edit_emotion=body_edit_emotion,
        body_force_edit_mode=body_force_edit_mode,
    )
    return finalize_runtime_context(
        foundation,
        addon_chat_owner=addon_chat_owner,
        addon_speech_owner=addon_speech_owner,
        addon_push_to_talk_owner=addon_push_to_talk_owner,
        addon_orb_owner=addon_orb_owner,
        addon_audio_story_owner=addon_audio_story_owner,
        addon_avatar_resource_owner=addon_avatar_resource_owner,
        addon_visual_request_owner=addon_visual_request_owner,
        prompt_refinement_owner=prompt_refinement_owner,
        application_dispatch=application_dispatch,
        application_run=application_run,
        application_request_stop=application_request_stop,
        application_config_update=application_config_update,
        application_activity=application_activity,
        application_stt_backend_catalog=application_stt_backend_catalog,
        application_stt_backend_reinitialize=application_stt_backend_reinitialize,
        application_tts_backend_catalog=application_tts_backend_catalog,
        application_tts_backend_reinitialize=application_tts_backend_reinitialize,
        application_avatar_catalog=application_avatar_catalog,
        application_avatar_select=application_avatar_select,
        application_body_snapshot=application_body_snapshot,
        application_body_set_live_sync=application_body_set_live_sync,
        application_body_select_emotion=application_body_select_emotion,
        application_body_update_pose=application_body_update_pose,
        application_body_update_profile=application_body_update_profile,
        application_body_update_hand_calibration=application_body_update_hand_calibration,
        application_bind_image_review=application_bind_image_review,
        application_bind_addon_manager_getter=application_bind_addon_manager_getter,
        application_bind_addon_event_publisher=application_bind_addon_event_publisher,
        application_queue_typed_chat=application_queue_typed_chat,
        application_replace_chat_session_history=application_replace_chat_session_history,
        application_delete_chat_message=application_delete_chat_message,
        application_edit_chat_history=application_edit_chat_history,
        application_conversation_actions=application_conversation_actions,
        application_reset_chat_session=application_reset_chat_session,
        application_export_chat_session=application_export_chat_session,
        application_import_chat_session=application_import_chat_session,
        application_submit_manual_interaction=application_submit_manual_interaction,
        application_set_memory_context_path=application_set_memory_context_path,
        application_set_memory_identity=application_set_memory_identity,
        application_set_memory_embedding_baseline=application_set_memory_embedding_baseline,
        application_schedule_memory_context_flush=application_schedule_memory_context_flush,
        application_memory_work_context_is_current=application_memory_work_context_is_current,
        application_bind_memory_updates=application_bind_memory_updates,
        application_memory_continuity_snapshot=application_memory_continuity_snapshot,
        application_memory_status_view=application_memory_status_view,
        application_memory_embedding_status=application_memory_embedding_status,
        application_memory_embedding_blocked_event=application_memory_embedding_blocked_event,
        application_memory_embedding_models=application_memory_embedding_models,
        application_schedule_memory_embedding_rebuild=application_schedule_memory_embedding_rebuild,
        application_schedule_memory_archive_candidate=application_schedule_memory_archive_candidate,
        application_update_continuity_memory=application_update_continuity_memory,
        application_schedule_continuity_memory_batch=application_schedule_continuity_memory_batch,
        application_clear_continuity_memory=application_clear_continuity_memory,
        application_schedule_long_term_memory_extract=application_schedule_long_term_memory_extract,
        application_memory_archive_snapshot=application_memory_archive_snapshot,
        application_memory_export_default_path=application_memory_export_default_path,
        application_export_session_memory_report=application_export_session_memory_report,
        application_retrieve_long_term_memory=application_retrieve_long_term_memory,
    )


def _raise_stale_visual():
    from core.runtime.visual import _StaleVisualCompletion

    raise _StaleVisualCompletion()


def start_runtime(context: RuntimeContext) -> CommandResult[None]:
    return context.lifecycle.start()


def stop_runtime(context: RuntimeContext) -> CommandResult[None]:
    result = context.lifecycle.stop()
    context.addons.close()
    return result


__all__ = [
    "RuntimeFoundation",
    "compose_runtime",
    "compose_runtime_foundation",
    "finalize_runtime_context",
    "start_runtime",
    "stop_runtime",
]
