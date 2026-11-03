"""Reference-only aggregate for explicitly composed runtime services."""

from __future__ import annotations

from dataclasses import dataclass

from core.runtime.addons import AddonGateway
from core.runtime.avatar import AvatarService
from core.runtime.body_profile import BodyProfileService
from core.runtime.config import RuntimeConfigService
from core.runtime.config_effects import RuntimeConfigEffects
from core.runtime.controllers import ControllerSetupRegistry
from core.runtime.conversation import ConversationService
from core.runtime.events import RuntimeEventBus
from core.runtime.facade import ApplicationFacade
from core.runtime.identity_relay import IdentityRelayService
from core.runtime.interaction import InteractionService
from core.runtime.lifecycle import RuntimeLifecycle, WorkerSupervisor
from core.runtime.memory import MemoryService
from core.runtime.memory_admin import MemoryAdminService
from core.runtime.playback import PlaybackService
from core.runtime.prompt_assembly import PromptAssemblyService
from core.runtime.providers import ProviderService
from core.runtime.proactive import ProactiveService
from core.runtime.replay import ReplayService
from core.runtime.sensory import SensoryService
from core.runtime.speech_input import SpeechInputService
from core.runtime.speech_output import SpeechOutputService
from core.runtime.turns import TurnCoordinator
from core.runtime.visual import VisualService


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    facade: ApplicationFacade
    config: RuntimeConfigService
    config_effects: RuntimeConfigEffects
    lifecycle: RuntimeLifecycle
    workers: WorkerSupervisor
    controllers: ControllerSetupRegistry
    conversation: ConversationService
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


__all__ = ["RuntimeContext"]
