"""Finite production ownership for realtime speech, playback, and effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from core import text_chunking
from core.runtime.avatar import AvatarService
from core.runtime.conversation import ConversationService
from core.runtime.controllers import ControllerSetupRegistry
from core.runtime.interaction import InteractionCapabilities
from core.runtime.lifecycle import WorkerSupervisor
from core.runtime.playback import AudioFilePlaybackCapabilities, AudioFilePlaybackDevice, PlaybackService
from core.runtime.replay import VoiceResolver
from core.runtime.sensory import SensoryCapabilities
from core.runtime.speech_input import SpeechInputCapabilities, SpeechInputTuning
from core.runtime.speech_output import SpeechOutputCapabilities, SpeechOutputService
from core.runtime.speech_routes import (
    NormalSpeechRouteCoordinator,
    SpeechRouteAddonGateway,
)
from core.runtime.visual import VisualCapabilities, VisualService

RealtimeEffect = Callable[[dict[str, object]], object]
RealtimeTrace = Callable[[str, dict[str, object]], object]


def _ignore_effect(_payload) -> None:
    return None


def _ignore_trace(_event, _fields) -> None:
    return None


class PreparedSentenceSplitterOwner(Protocol):
    """Prepare and retain the process-owned, IO-free sentence splitter."""

    def prepare(self) -> text_chunking.PreparedSentenceSplitter: ...

    def splitter(self) -> text_chunking.PreparedSentenceSplitter: ...


@dataclass(frozen=True, slots=True)
class ProductionTtsEvents:
    """One event set shared by generation, playback, replay, and ducking."""

    trace: Callable[[str, object], object] = _ignore_trace
    generation_started: Callable[[object], object] = _ignore_effect
    generation_finished: Callable[[object], object] = _ignore_effect
    audio_chunk_ready: Callable[[object], object] = _ignore_effect
    segment_started: Callable[[object], object] = _ignore_effect
    duck_start: Callable[[object], object] = _ignore_effect
    duck_end: Callable[[object], object] = _ignore_effect
    local_audio_progress: Callable[[object], object] = _ignore_effect


@dataclass(frozen=True, slots=True)
class ProductionSpeechInputOwner:
    """Own the concrete microphone capabilities and their fixed tuning."""

    capabilities: SpeechInputCapabilities
    tuning: SpeechInputTuning
    logger: Callable[[str], None] = print


@dataclass(frozen=True, slots=True)
class ProductionTtsOwner:
    """Own TTS generation callbacks and prepared sentence segmentation."""

    adapter_for: Callable[[object], object]
    sentence_splitter: PreparedSentenceSplitterOwner
    events: ProductionTtsEvents
    set_seed: Callable[[int], object] | None = None
    logger: Callable[[str], None] = print
    prepare_playback_audio: Callable[[object, object], object] | None = None
    incremental_pcm_allowed: Callable[[object, object], bool] | None = None

    def capabilities(self) -> SpeechOutputCapabilities:
        return SpeechOutputCapabilities(
            adapter_for=self.adapter_for,
            set_seed=self.set_seed,
            logger=self.logger,
            trace=self.events.trace,
            generation_started=self.events.generation_started,
            generation_finished=self.events.generation_finished,
            audio_chunk_ready=self.events.audio_chunk_ready,
            prepare_playback_audio=self.prepare_playback_audio,
            incremental_pcm_allowed=self.incremental_pcm_allowed,
        )

    def prepare_sentence_splitter(self) -> text_chunking.PreparedSentenceSplitter:
        return self.sentence_splitter.prepare()

    def create_routes(
        self,
        *,
        speech_output: SpeechOutputService,
        playback: PlaybackService,
        controllers: ControllerSetupRegistry,
        avatar: AvatarService,
        addons: SpeechRouteAddonGateway | None = None,
        before_speech: Callable[[str], CommandResult] | None = None,
    ) -> NormalSpeechRouteCoordinator:
        """Create routes only after tokenizer preparation, before realtime work."""

        prepared = self.prepare_sentence_splitter()
        return NormalSpeechRouteCoordinator(
            speech_output=speech_output,
            playback=playback,
            controllers=controllers,
            avatar=avatar,
            addons=addons,
            prepared_sentence_splitter=prepared,
            before_speech=before_speech,
        )


@dataclass(frozen=True, slots=True)
class ProductionPlaybackOwner:
    """Build the existing single-worker audio-file playback device."""

    play_file: Callable[..., object]
    delete_audio: Callable[[str], object]
    volume_for: Callable[[object, str], float]
    events: ProductionTtsEvents
    supports_audio_start: bool = False
    open_local_session: Callable[..., object] | None = None

    def create_device(self) -> AudioFilePlaybackDevice:
        return AudioFilePlaybackDevice(
            AudioFilePlaybackCapabilities(
                play_file=self.play_file,
                delete_audio=self.delete_audio,
                volume_for=self.volume_for,
                segment_started=self.events.segment_started,
                duck_start=self.events.duck_start,
                duck_end=self.events.duck_end,
                trace=self.events.trace,
                supports_audio_start=self.supports_audio_start,
                open_local_session=self.open_local_session,
            )
        )


@dataclass(frozen=True, slots=True)
class ProductionReplayOwner:
    """Own replay voice resolution and diagnostics.

    Replay remains orchestration over the same speech, playback, and avatar
    owners as a normal route.  It intentionally has no callback-heavy legacy
    playback session or second playback implementation.
    """

    resolve_voice: VoiceResolver
    events: ProductionTtsEvents


@dataclass(frozen=True, slots=True)
class ProductionVisualOwner:
    capabilities: VisualCapabilities
    request_id_factory: Callable[[], str]


@dataclass(frozen=True, slots=True)
class ProductionSensoryOwner:
    capabilities: SensoryCapabilities
    registry: object


@dataclass(frozen=True, slots=True)
class ProductionInteractionOwner:
    capabilities: InteractionCapabilities
    queue_size: int = 32

    def __post_init__(self) -> None:
        object.__setattr__(self, "queue_size", max(1, min(1024, int(self.queue_size))))


@dataclass(frozen=True, slots=True)
class PreparedProductionRealtime:
    """Typed inputs available before runtime service construction begins."""

    speech_input_capabilities: SpeechInputCapabilities
    speech_input_tuning: SpeechInputTuning
    speech_input_logger: Callable[[str], None]
    speech_output_capabilities: SpeechOutputCapabilities
    playback_device: AudioFilePlaybackDevice
    visual_capabilities: VisualCapabilities
    visual_request_id_factory: Callable[[], str]
    sensory_capabilities: SensoryCapabilities
    sensory_registry: object
    interaction_capabilities: InteractionCapabilities
    interaction_queue_size: int
    replay_voice_resolver: VoiceResolver
    replay_trace: Callable[[str, object], object]
    prepared_sentence_splitter: text_chunking.PreparedSentenceSplitter


@dataclass(frozen=True, slots=True)
class ProductionRealtimeOwners:
    """Finite production aggregate; each realtime domain has one named owner."""

    speech_input_owner: ProductionSpeechInputOwner
    tts_owner: ProductionTtsOwner
    playback_owner: ProductionPlaybackOwner
    replay_owner: ProductionReplayOwner
    visual_owner: ProductionVisualOwner
    sensory_owner: ProductionSensoryOwner
    interaction_owner: ProductionInteractionOwner

    def prepare(self) -> PreparedProductionRealtime:
        """Freeze startup inputs without constructing or locating runtime services."""

        splitter = self.tts_owner.prepare_sentence_splitter()
        return PreparedProductionRealtime(
            speech_input_capabilities=self.speech_input_owner.capabilities,
            speech_input_tuning=self.speech_input_owner.tuning,
            speech_input_logger=self.speech_input_owner.logger,
            speech_output_capabilities=self.tts_owner.capabilities(),
            playback_device=self.playback_owner.create_device(),
            visual_capabilities=self.visual_owner.capabilities,
            visual_request_id_factory=self.visual_owner.request_id_factory,
            sensory_capabilities=self.sensory_owner.capabilities,
            sensory_registry=self.sensory_owner.registry,
            interaction_capabilities=self.interaction_owner.capabilities,
            interaction_queue_size=self.interaction_owner.queue_size,
            replay_voice_resolver=self.replay_owner.resolve_voice,
            replay_trace=self.replay_owner.events.trace,
            prepared_sentence_splitter=splitter,
        )

    def create_normal_speech_routes(
        self,
        *,
        speech_output: SpeechOutputService,
        playback: PlaybackService,
        controllers: ControllerSetupRegistry,
        avatar: AvatarService,
        addons: SpeechRouteAddonGateway | None = None,
        before_speech: Callable[[str], CommandResult] | None = None,
    ) -> NormalSpeechRouteCoordinator:
        return self.tts_owner.create_routes(
            speech_output=speech_output,
            playback=playback,
            controllers=controllers,
            avatar=avatar,
            addons=addons,
            before_speech=before_speech,
        )

def build_production_realtime_owners(
    *,
    speech_input_owner: ProductionSpeechInputOwner,
    tts_owner: ProductionTtsOwner,
    playback_owner: ProductionPlaybackOwner,
    replay_owner: ProductionReplayOwner,
    visual_owner: ProductionVisualOwner,
    sensory_owner: ProductionSensoryOwner,
    interaction_owner: ProductionInteractionOwner,
) -> ProductionRealtimeOwners:
    """Retain the seven concrete realtime owners in one explicit record."""

    return ProductionRealtimeOwners(
        speech_input_owner=speech_input_owner,
        tts_owner=tts_owner,
        playback_owner=playback_owner,
        replay_owner=replay_owner,
        visual_owner=visual_owner,
        sensory_owner=sensory_owner,
        interaction_owner=interaction_owner,
    )


__all__ = [
    "PreparedProductionRealtime",
    "PreparedSentenceSplitterOwner",
    "ProductionInteractionOwner",
    "ProductionPlaybackOwner",
    "ProductionRealtimeOwners",
    "ProductionReplayOwner",
    "ProductionSensoryOwner",
    "ProductionSpeechInputOwner",
    "ProductionTtsEvents",
    "ProductionTtsOwner",
    "ProductionVisualOwner",
    "build_production_realtime_owners",
]
