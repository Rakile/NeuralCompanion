"""Concrete desktop composition for production conversation and addon owners."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from core import expression_state, sensory as sensory_core


def _publish_musetalk_audio_progress(addon_manager, fields):
    """Owned numeric update on the existing targeted, in-process addon seam."""
    return addon_manager.invoke_addon_capability(
        "nc.musetalk_avatar", "runtime.preview.set_state",
        {"state": dict(fields), "persist": False})

from core.conversation_flow_v2 import ProductionConversationServices
from core.runtime.conversation_addons import (
    ConversationAddonBinding,
    ConversationAddonOwner,
    build_conversation_addon_owner,
)
from core.runtime.conversation_owners import (
    ConversationHistoryRuntimeOwner,
    ConversationSessionRuntimeOwner,
    RuntimeConfigReader,
    UserImageRuntimeOwner,
)
from core.runtime.identity_relay import IdentityRelaySnapshotRegistry
from core.runtime.events import RuntimeEvent
from core.runtime.loop_control import (
    ConversationLoopControlOwner,
    DryRunReplyOwner,
)
from core.runtime.normal_chat import (
    NormalChatApplicationAdapter,
    NormalChatRuntime,
    PromptAssemblyNormalChatRequestAssembler,
)
from core.runtime.presence import AvatarPresenceOwner, PresenceVisualAuthority
from core.runtime.production_addon_extensions import (
    ProductionAddonRuntimeExtensionOwners,
    build_production_addon_runtime_extensions,
)
from core.runtime.production_addon_owners import (
    AvatarEmotionResourceOwner,
    CompanionOrbContextualReplyOwner,
    ProductionAudioStoryTtsRuntimeExtensionOwner,
    ProductionAvatarResourceRuntimeExtensionOwner,
    ProductionChatContextRuntimeExtensionOwner,
    ProductionOrbRuntimeExtensionOwner,
    ProductionPromptRefinementRuntimeExtensionOwner,
    ProductionPushToTalkRuntimeExtensionOwner,
    ProductionSpeechRuntimeExtensionOwner,
    ProductionVisualRequestRuntimeExtensionOwner,
    PushToTalkHoldOwner,
    build_production_addon_runtime_extension_owners,
)
from core.runtime.production_avatar import (
    AvatarAddonCapabilityGateway,
    ProductionAvatarOwner,
    ProductionAvatarPreviewState,
    ProductionAvatarRuntimeActions,
)
from core.runtime.production_compatibility import ProductionCompatibility
from core.runtime.production_desktop_addon_ports import (
    ProductionDesktopAddonManagerPort,
    ProductionDesktopIdentityRelaySessionPort,
)
from core.runtime.production_desktop_avatar_emotions import (
    ProductionDesktopAvatarEmotionCatalog,
)
from core.runtime.production_desktop_compatibility_owners import (
    ProductionDesktopChatViewOwner,
    ProductionDesktopMemoryTriggerOwner,
    ProductionDesktopScreenCaptureOwner,
)
from core.runtime.production_desktop_compatibility_ports import (
    ProductionDesktopCompatibilityBindings,
)
from core.runtime.production_desktop_graph_ports import (
    ProductionAudioStoryTtsResourceOwner,
    ProductionDesktopAvatarEmotionBinding,
    ProductionAvatarEmotionResourceOwner,
)
from core.runtime.avatar_assets import MuseTalkAssetStore
from core.runtime.avatar_visual import (
    AvatarVisualCapabilities,
    AvatarVisualCoordinator,
)
from core.runtime.production_composer import (
    DefaultProductionApplicationComposer,
    ProductionApplicationBindingEdges,
    ProductionApplicationComposer,
    ProductionCompositionRoots,
    ProductionConversationOwnerGraph,
)
from core.runtime.production_graph import build_production_conversation_application
from core.runtime.production_prompt import ProductionNormalChatPromptPlanBuilder
from core.runtime.production_realtime import ProductionRealtimeOwners
from core.runtime.production_desktop_realtime_ports import (
    ProductionDesktopRealtimeBindings,
)
from core.runtime.production_desktop_sensory import ProductionDesktopSensoryOwner
from core.runtime.sensory_policy import SensoryPolicy
from core.runtime.production_desktop_visual_history import (
    ProductionDesktopVisualHistoryOwner,
)
from core.runtime.production_session import (
    AssistantMemoryState,
    ProductionChatSessionOwner,
    SensoryHistorySanitizer,
)
from core.runtime.production_speech import (
    AssistantReplyNotifier,
    ProductionSpeechOutputOwner,
    SpeechLatencyRecorder,
)
from core.runtime.production_speech_backends import ProductionSpeechBackendOwner
from core.runtime.production_startup_ports import (
    EventState,
    ProductionProviderStartupPort,
    ProductionRuntimeLifecyclePort,
    ProductionSpeechStartupPort,
    ProductionStartupEnvironmentPort,
    ProductionStartupNoticeSink,
)
from core.runtime.prompt_tasks import PromptTaskService
from core.runtime.speech_routes import (
    VoiceSegment,
    VoiceSegmentationPolicy,
    VoiceSegmentationRequest,
)
from core.runtime.startup import ProductionStartupComposition


@dataclass(frozen=True, slots=True)
class ProductionDesktopGraphInputs:
    """Finite desktop leaves that remain outside the core runtime graph."""

    app_root: str | Path
    realtime: ProductionRealtimeOwners
    realtime_bindings: ProductionDesktopRealtimeBindings
    addon_manager: ProductionDesktopAddonManagerPort
    compatibility: ProductionCompatibility
    compatibility_bindings: ProductionDesktopCompatibilityBindings
    binding_edges: ProductionApplicationBindingEdges
    conversation_addon_binding: ConversationAddonBinding
    dry_run: DryRunReplyOwner
    avatar_runtime_actions: ProductionAvatarRuntimeActions
    avatar_preview_state: ProductionAvatarPreviewState
    avatar_addon_gateway: AvatarAddonCapabilityGateway
    avatar_hand_debug: Mapping[str, object]
    presence_visual: PresenceVisualAuthority
    reply_notifier: AssistantReplyNotifier
    speech_latency: SpeechLatencyRecorder
    sensory_history: SensoryHistorySanitizer
    push_to_talk_hold: PushToTalkHoldOwner
    push_to_talk_held: EventState
    contextual_replies: CompanionOrbContextualReplyOwner
    avatar_emotions: ProductionDesktopAvatarEmotionBinding
    seam_debug_directory: str | Path
    logger: Callable[[str], object] = print

    def __post_init__(self) -> None:
        if not isinstance(self.app_root, (str, Path)) or not str(self.app_root).strip():
            raise TypeError("app_root must be a non-empty path.")
        required = {
            "realtime": self.realtime,
            "realtime_bindings": self.realtime_bindings,
            "addon_manager": self.addon_manager,
            "compatibility": self.compatibility,
            "compatibility_bindings": self.compatibility_bindings,
            "binding_edges": self.binding_edges,
            "conversation_addon_binding": self.conversation_addon_binding,
            "dry_run": self.dry_run,
            "avatar_runtime_actions": self.avatar_runtime_actions,
            "avatar_preview_state": self.avatar_preview_state,
            "avatar_addon_gateway": self.avatar_addon_gateway,
            "presence_visual": self.presence_visual,
            "reply_notifier": self.reply_notifier,
            "speech_latency": self.speech_latency,
            "sensory_history": self.sensory_history,
            "push_to_talk_hold": self.push_to_talk_hold,
            "push_to_talk_held": self.push_to_talk_held,
            "contextual_replies": self.contextual_replies,
            "avatar_emotions": self.avatar_emotions,
        }
        missing = tuple(name for name, value in required.items() if value is None)
        if missing:
            raise TypeError(
                "Missing required production desktop ports: " + ", ".join(missing)
            )
        if not isinstance(self.avatar_hand_debug, Mapping):
            raise TypeError("avatar_hand_debug must be a mapping.")
        if not isinstance(
            self.realtime_bindings,
            ProductionDesktopRealtimeBindings,
        ):
            raise TypeError(
                "realtime_bindings must be ProductionDesktopRealtimeBindings."
            )
        if not isinstance(
            self.addon_manager,
            ProductionDesktopAddonManagerPort,
        ):
            raise TypeError(
                "addon_manager must be ProductionDesktopAddonManagerPort."
            )
        if not isinstance(
            self.compatibility_bindings,
            ProductionDesktopCompatibilityBindings,
        ):
            raise TypeError(
                "compatibility_bindings must be "
                "ProductionDesktopCompatibilityBindings."
            )
        callbacks = {"logger": self.logger}
        invalid_callbacks = tuple(
            name for name, callback in callbacks.items() if not callable(callback)
        )
        if invalid_callbacks:
            raise TypeError(
                "Production desktop callbacks must be callable: "
                + ", ".join(invalid_callbacks)
            )


@dataclass(frozen=True, slots=True)
class _CompletedDesktopGraph:
    roots: ProductionCompositionRoots
    graph: ProductionConversationOwnerGraph
    addons: ProductionAddonRuntimeExtensionOwners


class ProductionDesktopGraphFactory:
    """Build one owner graph and publish its completed addon owners second."""

    __slots__ = ("_inputs", "_pending")

    def __init__(self, inputs: ProductionDesktopGraphInputs) -> None:
        if not isinstance(inputs, ProductionDesktopGraphInputs):
            raise TypeError(
                "Production desktop graph factory requires named desktop inputs."
            )
        self._inputs = inputs
        self._pending: _CompletedDesktopGraph | None = None

    def graph_factory(
        self,
        roots: ProductionCompositionRoots,
    ) -> ProductionConversationOwnerGraph:
        if self._pending is not None:
            raise RuntimeError(
                "A production desktop graph is awaiting addon completion."
            )
        graph, addon_owners = self._build(roots)
        self._pending = _CompletedDesktopGraph(roots, graph, addon_owners)
        return graph

    def addon_factory(
        self,
        roots: ProductionCompositionRoots,
        graph: ProductionConversationOwnerGraph,
    ) -> ProductionAddonRuntimeExtensionOwners:
        completed = self._pending
        if (
            completed is None
            or completed.roots is not roots
            or completed.graph is not graph
        ):
            raise RuntimeError(
                "Production desktop addon completion requires its matching graph."
            )
        self._pending = None
        return completed.addons

    def _build(
        self,
        roots: ProductionCompositionRoots,
    ) -> tuple[
        ProductionConversationOwnerGraph,
        ProductionAddonRuntimeExtensionOwners,
    ]:
        if not isinstance(roots, ProductionCompositionRoots):
            raise TypeError("Production desktop composition requires named roots.")
        inputs = self._inputs
        foundation = roots.foundation
        from core.communication_trace import CommunicationTrace
        import atexit
        if getattr(foundation.providers,'communication_trace',None) is None:
            foundation.providers.communication_trace=CommunicationTrace(Path(inputs.app_root)/'runtime'/'communication_logs')
            atexit.register(foundation.providers.communication_trace.stop)
        compatibility = inputs.compatibility
        realtime_bindings = inputs.realtime_bindings

        realtime_bindings.config.bind(foundation.config)
        realtime_bindings.barge_in.bind(foundation.speech_input)
        realtime_bindings.addons.bind(inputs.addon_manager)
        inputs.conversation_addon_binding.bind(inputs.addon_manager)

        control = ConversationLoopControlOwner(
            interaction=foundation.interaction,
            config=foundation.config,
            playback=foundation.playback,
            logger=inputs.logger,
        )
        control_events = realtime_bindings.control_events
        control_events.stop_requested.bind(control.controls.stop)
        control_events.audio_playing.bind(control.controls.audio_playing)
        control_events.microphone_active.bind(control.controls.microphone)
        speech_backends = ProductionSpeechBackendOwner(
            config=foundation.config,
            logger=inputs.logger,
        )
        realtime_bindings.speech_backends.bind(speech_backends)
        avatar_emotions = ProductionDesktopAvatarEmotionCatalog(
            app_root=inputs.app_root,
            config=foundation.config,
            body=foundation.body_profile,
            addons=inputs.addon_manager,
        )
        avatar_resources: AvatarEmotionResourceOwner = (
            ProductionAvatarEmotionResourceOwner(
                avatar_emotions.refresh_emotions,
                speech_backends,
            )
        )
        dry_run = inputs.dry_run
        realtime_bindings.seed.bind(dry_run)
        audio_story_tts = ProductionAudioStoryTtsResourceOwner(
            seed=dry_run,
            speech=speech_backends,
        )
        realtime_bindings.visual_history.bind(
            ProductionDesktopVisualHistoryOwner(
                conversation=foundation.conversation,
                visual=foundation.visual,
                memory=roots.memory,
            )
        )
        avatar = ProductionAvatarOwner(
            config=foundation.config,
            avatar=foundation.avatar,
            body=foundation.body_profile,
            runtime_actions=inputs.avatar_runtime_actions,
            stop_requested=control.controls.stop,
            playback_stop_requested=control.controls.stop_playback,
            preview_state=inputs.avatar_preview_state,
            hand_debug=inputs.avatar_hand_debug,
            worker_supervisor=foundation.workers,
            work_lease_source=_ConversationLeaseSource(foundation.conversation),
            addon_gateway=inputs.avatar_addon_gateway,
            logger=inputs.logger,
        )
        musetalk_assets = MuseTalkAssetStore(
            Path(inputs.app_root).resolve()
            / "MuseTalk"
            / "runtime"
            / "rendered_chunks",
            seam_debug_root=inputs.seam_debug_directory,
        )

        def invoke_musetalk(
            capability: str,
            payload: Mapping[str, object] | None = None,
        ) -> object:
            return inputs.addon_manager.invoke_addon_capability(
                "nc.musetalk_avatar",
                capability,
                dict(payload or {}),
            )

        def runtime_config() -> dict[str, object]:
            return dict(foundation.config.snapshot().values)

        def frame_snapshot() -> Mapping[str, object]:
            result = invoke_musetalk("runtime.preview.current_state")
            return dict(result) if isinstance(result, Mapping) else {}

        def visual_lease_is_current(lease) -> bool:
            if lease.turn_id is not None:
                return foundation.turns.committed_effect_lease_is_valid(lease)
            return foundation.conversation.session_lease_is_current(lease)

        def publish_frame(state: Mapping[str, object]) -> object:
            return inputs.avatar_preview_state.set_current_musetalk_frame_data(
                dict(state)
            )

        def reset_pipeline() -> object:
            return invoke_musetalk("runtime.pipeline.reset")

        def prime_frame(state: Mapping[str, object]) -> object:
            return invoke_musetalk(
                "runtime.preview.prime_frame",
                {
                    "playback_state": dict(state),
                    "runtime_config": runtime_config(),
                },
            )

        def stream_frames(state: Mapping[str, object], stop_signal: object) -> object:
            return invoke_musetalk(
                "runtime.preview.stream_frames",
                {
                    "playback_state": dict(state),
                    "stop_event": stop_signal,
                    "runtime_config": runtime_config(),
                },
            )

        def stream_audio_progress(
            state: Mapping[str, object],
            stop_signal: object,
        ) -> object:
            return invoke_musetalk(
                "runtime.preview.stream_delegated_audio_progress",
                {
                    "playback_state": dict(state),
                    "stop_event": stop_signal,
                },
            )

        def estimate_displayed_frames(
            state: Mapping[str, object],
            now: float | None,
        ) -> int:
            return int(
                invoke_musetalk(
                    "runtime.preview.estimate_displayed_frames",
                    {
                        "state": dict(state),
                        "now": now,
                        "runtime_config": runtime_config(),
                    },
                )
                or 0
            )

        def current_source_index(
            state: Mapping[str, object],
            advance: bool,
        ) -> int:
            return int(
                invoke_musetalk(
                    "runtime.preview.current_source_index",
                    {
                        "state": dict(state),
                        "advance_to_next_frame": bool(advance),
                        "runtime_config": runtime_config(),
                    },
                )
                or 0
            )

        def preview_stream_enabled() -> bool:
            disabled = str(
                os.environ.get(
                    "NC_MUSETALK_DISABLE_PREVIEW_STREAM_THREAD",
                    "",
                )
                or ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            return not disabled and bool(
                foundation.config.get(
                    "ua_companion_orb_send_musetalk_face_mask",
                    False,
                )
            )

        def visual_fps() -> int:
            return int(foundation.config.get("musetalk_fps", 24) or 24)

        visual_capabilities = AvatarVisualCapabilities(
            frame_snapshot=frame_snapshot,
            publish_frame=publish_frame,
            reset_expression=expression_state.reset_current_expression_data,
            reset_pipeline=reset_pipeline,
            prime_frame=prime_frame,
            stream_frames=stream_frames,
            stream_audio_progress=stream_audio_progress,
            estimate_displayed_frames=estimate_displayed_frames,
            current_source_index=current_source_index,
            preview_stream_enabled=preview_stream_enabled,
            shutdown_requested=control.controls.stop.is_set,
            cleanup_blocked=control.controls.audio_playing.is_set,
            fps=visual_fps,
            publish_audio_progress=lambda fields: _publish_musetalk_audio_progress(inputs.addon_manager, fields),
        )

        avatar_visual = AvatarVisualCoordinator(
            workers=foundation.workers,
            adapter=avatar.active_adapter,
            lease_is_current=visual_lease_is_current,
            capabilities=visual_capabilities,
            assets=musetalk_assets,
        )
        _require_command(
            foundation.avatar.attach_visual_coordinator(avatar_visual),
            "Could not attach the avatar visual runtime.",
        )

        route_addons = _RequiredSpeechRouteAddonBinding()
        routes = inputs.realtime.create_normal_speech_routes(
            speech_output=foundation.speech_output,
            playback=foundation.playback,
            controllers=foundation.controllers,
            avatar=foundation.avatar,
            addons=route_addons,
            before_speech=foundation.replay.cancel_all,
        )
        from core.runtime.structured_character_voice import CharacterVoiceTurns
        character_voice_turns = CharacterVoiceTurns(
            lambda conversation, backend: inputs.addon_manager.invoke_addon_capability(
                'nc.multi_persona_roleplay', 'chat_characters',
                {'action':'voice-context','conversation_id':conversation,'tts_backend':backend}),
            lambda conversation, names: inputs.addon_manager.invoke_addon_capability(
                'nc.multi_persona_roleplay','chat_characters',
                {'action':'propose-candidates','conversation_id':conversation,'names':names}))
        speech_output = ProductionSpeechOutputOwner(
            speech_output=foundation.speech_output,
            routes=routes,
            visual=foundation.visual,
            config=foundation.config,
            leases=_ConversationLeaseSource(foundation.conversation),
            effect_admission=foundation.turns,
            notifier=inputs.reply_notifier,
            latency=inputs.speech_latency,
            available_emotions=avatar_emotions.available_names,
            supported_sound_tags=speech_backends.supported_sound_tag_names,
            communication_trace=foundation.providers.communication_trace,
            character_voice_turns=character_voice_turns,
        )

        config_reader = _LiveRuntimeConfigReader(foundation.config)
        normal_runtime = NormalChatRuntime.compose(
            conversation=foundation.conversation,
            turns=foundation.turns,
            providers=foundation.providers,
            identity_relay=foundation.identity_relay,
            workers=foundation.workers,
            assembler=PromptAssemblyNormalChatRequestAssembler(
                prompts=foundation.prompt_assembly,
                plans=ProductionNormalChatPromptPlanBuilder(
                    config=foundation.config,
                    conversation=foundation.conversation,
                    providers=foundation.providers,
                    addons=compatibility.addons,
                    memory=roots.memory.memory,
                    conversation_tools_enabled=True,
                    character_voice_turns=character_voice_turns,
                ),
            ),
        )
        normal_chat = NormalChatApplicationAdapter(
            normal_runtime,
            character_voice_turns=character_voice_turns,
            continuous_audio_stage=speech_output.stage_continuous_audio,
            continuous_audio_activate=speech_output.activate_continuous_audio,
            continuous_audio_discard=speech_output.discard_continuous_audio,
            blocked_error=control.blocked_error,
            memory_work_context=roots.memory.current_work_context,
            visual_tail_filter=foundation.visual.strip_visual_tail,
            visual_prefix_checker=foundation.visual.looks_like_tag_prefix,
            hidden_request_guard=foundation.sensory.orb_watch_candidate_is_current,
            hidden_reply_delivered=foundation.sensory.orb_watch_reply_delivered,
            hidden_reply_publication=foundation.sensory.publish_orb_watch_reply,
            conversation_tools=(lambda operation, fields: inputs.addon_manager.invoke_addon_capability(
                'nc.companion_orb_overlay', 'companion_orb.conversation_tools',
                dict(fields, operation=operation))),
            mcp_conversation_tools=(lambda operation, fields: inputs.addon_manager.invoke_addon_capability(
                'nc.chat_mcp_tools', 'chat_mcp.conversation', dict(fields, operation=operation,
                    current_persona=lambda: str(foundation.config.get('active_quick_persona_id', '') or '')))),
            mcp_model_notice=lambda request, message: foundation.events.publish(RuntimeEvent(
                'chat.mcp_model_unsupported', {'message': message}, request.lease)),
        )
        session = ConversationSessionRuntimeOwner(
            foundation.conversation,
            config_reader,
            relay_metadata=compatibility.conversation.relay_metadata,
            chat_view=compatibility.conversation.chat_view,
            transactions=compatibility.conversation.transactions,
        )
        history = ConversationHistoryRuntimeOwner(
            foundation.conversation,
            config_reader,
            relay_metadata=compatibility.conversation.relay_metadata,
            committer=compatibility.conversation.committer,
            chat_view=compatibility.conversation.chat_view,
            transactions=compatibility.conversation.transactions,
            memory=compatibility.conversation.memory,
        )
        user_images = UserImageRuntimeOwner(
            policy=compatibility.conversation.user_image_policy,
            screen_capture=compatibility.conversation.screen_capture,
            logger=inputs.logger,
        )
        chat_session = ProductionChatSessionOwner(
            config=foundation.config,
            conversation=foundation.conversation,
            session=session,
            history=history,
            user_images=user_images,
            normal_chat=normal_chat,
            assistant_memory=AssistantMemoryState(),
            memory=foundation.memory,
            session_memory=roots.memory,
            identity_relay=compatibility.identity_relay.session,
            relay_snapshots=IdentityRelaySnapshotRegistry(),
            sensory=foundation.sensory,
            sensory_history=inputs.sensory_history,
            proactive=foundation.proactive,
            replay=foundation.replay,
            visual=foundation.visual,
            restore_avatar_presentation=foundation.avatar.reset_session_presentation,
            logger=inputs.logger,
        )

        prompt_tasks = PromptTaskService()
        chat_context_owner = ProductionChatContextRuntimeExtensionOwner(
            config=foundation.config,
            providers=foundation.providers,
            conversation=foundation.conversation,
            normal_chat=normal_chat,
            session=session,
            user_images=user_images,
            addon_contexts=compatibility.addons,
            session_exporter=chat_session,
        )
        from core.runtime.phone_reply_controls import PhoneReplyControls
        phone_reply_controls = PhoneReplyControls(
            foundation.conversation, history, normal_chat,
            chat_context_owner.submit_accepted_turn,
        )
        session.set_pending_replacement_listener(phone_reply_controls.pending_replaced)
        from core.runtime.conversation_actions import ConversationActionOwner
        conversation_actions = ConversationActionOwner(foundation.conversation,
            foundation.interaction, normal_chat, session)
        phone_reply_controls.port().conversation_actions = conversation_actions.port()
        chat_context_owner.bind_phone_reply_controls(phone_reply_controls.port())
        addon_owners = build_production_addon_runtime_extension_owners(
            chat_context_owner=chat_context_owner,
            speech_owner=ProductionSpeechRuntimeExtensionOwner(
                playback=foundation.playback,
                turns=foundation.turns,
                speech_model=speech_backends,
                speech_output=speech_output,
            ),
            push_to_talk_owner=ProductionPushToTalkRuntimeExtensionOwner(
                config=foundation.config,
                hold=inputs.push_to_talk_hold,
            ),
            orb_owner=ProductionOrbRuntimeExtensionOwner(
                config=foundation.config,
                providers=foundation.providers,
                prompt_tasks=prompt_tasks,
                conversation=foundation.conversation,
                playback=foundation.playback,
                speech_input=foundation.speech_input,
                sensory=foundation.sensory,
                provider_activity=foundation.providers,
                contextual_replies=inputs.contextual_replies,
            ),
            audio_story_tts_owner=ProductionAudioStoryTtsRuntimeExtensionOwner(
                config=foundation.config,
                avatar=foundation.avatar,
                resources=audio_story_tts,
            ),
            avatar_resource_owner=ProductionAvatarResourceRuntimeExtensionOwner(
                resources=avatar_resources,
            ),
            visual_request_owner=ProductionVisualRequestRuntimeExtensionOwner(
                config=foundation.config,
                conversation=foundation.conversation,
                visual=foundation.visual,
            ),
            prompt_refinement_owner=ProductionPromptRefinementRuntimeExtensionOwner(
                config=foundation.config,
                providers=foundation.providers,
                prompt_tasks=prompt_tasks,
            ),
        )
        conversation_addons = build_conversation_addon_owner(
            gateway=foundation.addons,
            extensions=build_production_addon_runtime_extensions(addon_owners),
            binding=inputs.conversation_addon_binding,
        )
        route_addons.bind(conversation_addons)

        presence = AvatarPresenceOwner(
            avatar=foundation.avatar,
            config=foundation.config,
            conversation=foundation.conversation,
            lease=foundation.conversation.session_lease(),
            visual=inputs.presence_visual,
        )
        realtime_bindings.sensory.bind(
            ProductionDesktopSensoryOwner(
                app_root=inputs.app_root,
                policy=SensoryPolicy(sensory_core.get_registry()),
                config=foundation.config,
                control=control,
                conversation=foundation.conversation,
                session=session,
                avatar=foundation.avatar,
                presence=inputs.presence_visual,
                proactive=foundation.proactive,
                visual=foundation.visual,
                addons=inputs.addon_manager,
                provider_activity=foundation.providers,
                available_emotions=avatar_emotions.available_names,
                speech_ready=speech_backends.ready,
                logger=inputs.logger,
            )
        )
        services = ProductionConversationServices(
            session=session,
            history=history,
            user_images=user_images,
            normal_chat=normal_chat,
            control=control,
            speech_input=foundation.speech_input,
            speech_output=speech_output,
            dry_run=dry_run,
            addons=conversation_addons,
            presence=presence,
            sensory=foundation.sensory,
            proactive=foundation.proactive,
            interaction=foundation.interaction,
            replay=foundation.replay,
            phone_reply_controls=phone_reply_controls,
            conversation_actions=conversation_actions,
        )
        missing = services.missing_domains()
        if missing:
            raise RuntimeError(
                "Production desktop conversation graph is incomplete: "
                + ", ".join(missing)
            )
        application = build_production_conversation_application(
            foundation.config.snapshot().values,
            turns=foundation.turns,
            services=services,
        )
        provider_startup = ProductionProviderStartupPort(
            foundation.config, foundation.providers, logger=inputs.logger,
            capture_provider_selection=lambda: foundation.turns.capture_detached_selection()[1],
            cancel_token=control.controls.stop)
        startup = ProductionStartupComposition(
            runtime_use=foundation.runtime_use,
            environment=ProductionStartupEnvironmentPort(
                foundation.config,
                control.controls.stop,
                clear_avatar_stream_state=lambda: foundation.avatar.clear_visual_state(
                    foundation.conversation.session_lease()
                ),
                runtime_cleanup=lambda: musetalk_assets.cleanup(
                    max_keep=64,
                    force=False,
                ),
                sentence_tokenizer_prepare=(
                    inputs.realtime.tts_owner.prepare_sentence_splitter
                ),
                seam_debug_directory=inputs.seam_debug_directory,
                capture_provider_selection=lambda: foundation.turns.capture_detached_selection()[1],
                on_provider_selection=provider_startup.bind_startup_selection,
            ),
            providers=provider_startup,
            avatar=_ProductionDesktopAvatarStartup(avatar),
            speech=ProductionSpeechStartupPort(
                foundation.config,
                foundation.speech_input,
                initialize_tts=speech_backends.reinitialize_tts_backend,
                release_session_resources=speech_backends.release_session_resources,
                finalize_session_resources=speech_backends.finalize_session_resources,
            ),
            lifecycle=ProductionRuntimeLifecyclePort(
                foundation.lifecycle,
                foundation.addons,
                control.controls.stop,
                listening_active=control.controls.listening,
                microphone_active=control.controls.microphone,
                push_to_talk_held=inputs.push_to_talk_held,
            ),
            application=application,
            notices=ProductionStartupNoticeSink(inputs.logger),
        )
        graph = ProductionConversationOwnerGraph(
            startup=startup,
            control=control,
            avatar=avatar,
            speech_backends=speech_backends,
            chat_session=chat_session,
            conversation_actions=conversation_actions.port(),
            binding_edges=_desktop_binding_edges(inputs, speech_backends),
        )
        compatibility_bindings = inputs.compatibility_bindings
        inputs.avatar_emotions.bind(avatar_emotions)
        compatibility_bindings.conversation.bind(foundation.conversation)
        compatibility_bindings.pending_turn.bind(session)
        compatibility_bindings.runtime_config.bind(foundation.config)
        compatibility_bindings.chat_view.bind(
            ProductionDesktopChatViewOwner(inputs.logger)
        )
        compatibility_bindings.assistant_commit.bind(normal_chat)
        compatibility_bindings.memory_triggers.bind(
            ProductionDesktopMemoryTriggerOwner(roots.memory, chat_session)
        )
        compatibility_bindings.screen_capture.bind(
            ProductionDesktopScreenCaptureOwner(
                sensory=foundation.sensory,
                config=foundation.config,
                conversation=foundation.conversation,
            )
        )
        compatibility_bindings.identity_relay_session.bind(
            ProductionDesktopIdentityRelaySessionPort(inputs.addon_manager)
        )
        return graph, addon_owners


class _LiveRuntimeConfigReader(RuntimeConfigReader):
    __slots__ = ("_config",)

    def __init__(self, config) -> None:
        self._config = config

    def current(self) -> Mapping[str, object]:
        return self._config.snapshot().values


class _ConversationLeaseSource:
    __slots__ = ("_conversation",)

    def __init__(self, conversation) -> None:
        self._conversation = conversation

    def current(self):
        return self._conversation.session_lease()

    def current_speech_lease(self):
        return self.current()


class _RequiredSpeechRouteAddonBinding:
    """Resolve the constructor cycle and fail if published before completion."""

    __slots__ = ("_lock", "_owner")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: ConversationAddonOwner | None = None

    def bind(self, owner: ConversationAddonOwner) -> None:
        if not isinstance(owner, ConversationAddonOwner):
            raise TypeError(
                "Speech route addon binding requires ConversationAddonOwner."
            )
        with self._lock:
            if self._owner is not None:
                raise RuntimeError("Speech route addon binding is already complete.")
            self._owner = owner

    def addon_voice_segments_stream_policy(
        self,
        config: Mapping[str, object],
    ) -> dict[str, object]:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError("Speech route addons were used before graph completion.")
        return owner.addon_voice_segments_stream_policy(config)

    def voice_stream_policy(
        self,
        request: VoiceSegmentationRequest,
    ) -> VoiceSegmentationPolicy:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError("Speech route addons were used before graph completion.")
        return owner.voice_stream_policy(request)

    def voice_segments(
        self,
        request: VoiceSegmentationRequest,
    ) -> tuple[VoiceSegment, ...]:
        with self._lock:
            owner = self._owner
        if owner is None:
            raise RuntimeError("Speech route addons were used before graph completion.")
        return owner.voice_segments(request)


class _ProductionDesktopAvatarStartup:
    __slots__ = ("_owner",)

    def __init__(self, owner: ProductionAvatarOwner) -> None:
        self._owner = owner

    def start(self, _avatar_mode: str):
        attached = self._owner.attach_selected()
        _require_command(attached, "Could not attach the selected avatar.")
        started = self._owner.start()
        _require_command(started, "Could not start the selected avatar.")
        return attached.value

    def warm_up(self, _avatar: object) -> None:
        _require_command(self._owner.warm_up(), "Could not warm up MuseTalk.")

    def set_idle(self) -> None:
        _require_command(self._owner.set_idle(), "Could not set MuseTalk idle state.")

    def stop(self) -> CommandResult[None]:
        return self._owner.stop()


def _desktop_binding_edges(
    inputs: ProductionDesktopGraphInputs,
    speech_backends: ProductionSpeechBackendOwner,
) -> ProductionApplicationBindingEdges:
    edges = inputs.binding_edges
    manager_bindings = [
        inputs.addon_manager.bind_manager_getter,
        speech_backends.bind_addon_manager_getter,
        inputs.compatibility.addons.bind_addon_manager_getter,
    ]
    if edges.bind_addon_manager_getter is not None:
        manager_bindings.append(edges.bind_addon_manager_getter)

    def bind_manager_getter(getter: Callable[..., object]) -> Callable[[], None]:
        unbinders = [binding(getter) for binding in manager_bindings]

        def unbind() -> None:
            for callback in reversed(unbinders):
                callback()

        return unbind

    return replace(edges, bind_addon_manager_getter=bind_manager_getter)


def _require_command(result, fallback: str) -> None:
    if result.accepted:
        return
    failure = result.failure
    raise RuntimeError(failure.message if failure is not None else fallback)


def build_default_production_desktop_application_composer(
    inputs: ProductionDesktopGraphInputs,
) -> ProductionApplicationComposer:
    """Create the default composer with one matched desktop factory pair."""

    factories = ProductionDesktopGraphFactory(inputs)
    return DefaultProductionApplicationComposer(
        graph_factory=factories.graph_factory,
        addon_factory=factories.addon_factory,
    )


__all__ = [
    "ProductionDesktopGraphFactory",
    "ProductionDesktopGraphInputs",
    "build_default_production_desktop_application_composer",
]
