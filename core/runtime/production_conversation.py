"""Finite, engine-free composition for the production conversation loop."""

from __future__ import annotations

from core.conversation_flow_v2 import ProductionConversationServices
from core.runtime.conversation_addons import ConversationAddonOwner
from core.runtime.conversation_owners import (
    ConversationHistoryRuntimeOwner,
    ConversationSessionRuntimeOwner,
    UserImageRuntimeOwner,
)
from core.runtime.interaction import InteractionService
from core.runtime.loop_control import (
    ConversationLoopControlOwner,
    DryRunReplyOwner,
)
from core.runtime.normal_chat import (
    NormalChatApplicationAdapter,
    NormalChatRuntime,
)
from core.runtime.presence import AvatarPresenceOwner
from core.runtime.proactive import ProactiveService
from core.runtime.production_speech import ProductionSpeechOutputOwner
from core.runtime.replay import ReplayService
from core.runtime.sensory import SensoryService
from core.runtime.speech_input import SpeechInputService


def build_production_conversation_services(
    *,
    session: ConversationSessionRuntimeOwner,
    history: ConversationHistoryRuntimeOwner,
    user_images: UserImageRuntimeOwner,
    normal_chat_runtime: NormalChatRuntime,
    control: ConversationLoopControlOwner,
    speech_input: SpeechInputService,
    speech_output: ProductionSpeechOutputOwner,
    dry_run: DryRunReplyOwner,
    addons: ConversationAddonOwner,
    presence: AvatarPresenceOwner,
    sensory: SensoryService,
    proactive: ProactiveService,
    interaction: InteractionService,
    replay: ReplayService,
) -> ProductionConversationServices:
    """Bind the concrete production owners to the loop's finite service graph."""

    services = ProductionConversationServices(
        session=session,
        history=history,
        user_images=user_images,
        normal_chat=NormalChatApplicationAdapter(
            normal_chat_runtime,
            blocked_error=control.blocked_error,
            hidden_request_guard=getattr(sensory, 'orb_watch_candidate_is_current', None),
            hidden_reply_delivered=getattr(sensory, 'orb_watch_reply_delivered', None),
        ),
        control=control,
        speech_input=speech_input,
        speech_output=speech_output,
        dry_run=dry_run,
        addons=addons,
        presence=presence,
        sensory=sensory,
        proactive=proactive,
        interaction=interaction,
        replay=replay,
    )
    missing = services.missing_domains()
    if missing:
        raise ValueError(
            "Production conversation services are incomplete: "
            + ", ".join(missing)
        )
    return services


__all__ = ["build_production_conversation_services"]
