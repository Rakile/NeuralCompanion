"""Concrete platform composition for production realtime runtime owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core import audio_playback, runtime_files, runtime_hotkeys, sensory
from core.runtime.interaction import InteractionCapabilities
from core.runtime.production_realtime import (
    PreparedSentenceSplitterOwner,
    ProductionInteractionOwner,
    ProductionPlaybackOwner,
    ProductionRealtimeOwners,
    ProductionReplayOwner,
    ProductionSensoryOwner,
    ProductionSpeechInputOwner,
    ProductionTtsEvents,
    ProductionTtsOwner,
    ProductionVisualOwner,
    build_production_realtime_owners,
)
from core.runtime.sensory import SensoryCapabilities
from core.runtime.speech_input import SpeechInputCapabilities, SpeechInputTuning
from core.runtime.visual import VisualCapabilities


def _require_callable(name: str, value: object) -> None:
    if not callable(value):
        raise TypeError(f"{name} must be callable")


@dataclass(frozen=True, slots=True)
class ProductionSpeechInputPlatform:
    """Finite process adapters required by the microphone/STT owner."""

    recognizer: object
    microphone_factory: Callable[..., object]
    microphone_names: Callable[[], object]
    addon_resolver: Callable[[str], object]
    speech_module: object
    audio_data_factory: Callable[..., object]
    microphone_active: object
    push_to_talk_held: Callable[[], bool]
    set_push_to_talk_hold: Callable[[bool], object]
    np_module: object
    tuning: SpeechInputTuning
    logger: Callable[[str], None] = print
    transcribe: Callable[..., object] | None = None
    pcm_callback: Callable[[bytes, int, int], object] | None = None

    def capabilities(self) -> SpeechInputCapabilities:
        for name in (
            "microphone_factory",
            "microphone_names",
            "addon_resolver",
            "audio_data_factory",
            "push_to_talk_held",
            "set_push_to_talk_hold",
            "logger",
        ):
            _require_callable(f"speech_input.{name}", getattr(self, name))
        if self.transcribe is not None:
            _require_callable("speech_input.transcribe", self.transcribe)
        if self.pcm_callback is not None:
            _require_callable("speech_input.pcm_callback", self.pcm_callback)
        if not isinstance(self.tuning, SpeechInputTuning):
            raise TypeError("speech_input.tuning must be SpeechInputTuning")
        return SpeechInputCapabilities(
            recognizer=self.recognizer,
            microphone_factory=self.microphone_factory,
            microphone_names=self.microphone_names,
            addon_resolver=self.addon_resolver,
            transcribe=self.transcribe,
            speech_module=self.speech_module,
            audio_data_factory=self.audio_data_factory,
            microphone_active=self.microphone_active,
            push_to_talk_held=self.push_to_talk_held,
            set_push_to_talk_hold=self.set_push_to_talk_hold,
            np_module=self.np_module,
            pcm_callback=self.pcm_callback,
        )


@dataclass(frozen=True, slots=True)
class ProductionTtsPlatform:
    """TTS adapter selection, sentence preparation, and observable effects."""

    adapter_for: Callable[[object], object]
    sentence_splitter: PreparedSentenceSplitterOwner
    events: ProductionTtsEvents
    set_seed: Callable[[int], object] | None = None
    logger: Callable[[str], None] = print
    prepare_playback_audio: Callable[[object, object], object] | None = None
    incremental_pcm_allowed: Callable[[object, object], bool] | None = None


@dataclass(frozen=True, slots=True)
class ProductionPlaybackPlatform:
    """Audio-device policy layered over core-owned file playback leaves."""

    volume_for: Callable[[object, str], float]
    events: ProductionTtsEvents
    play_file: Callable[..., object] = audio_playback.play_audio_file
    delete_audio: Callable[[str], object] = runtime_files.safe_delete_with_retry
    supports_audio_start: bool = False
    open_local_session: Callable[..., object] | None = None


@dataclass(frozen=True, slots=True)
class ProductionReplayPlatform:
    """Replay voice resolution and diagnostics over shared runtime owners."""

    events: ProductionTtsEvents
    resolve_voice: Callable[[object], str] = runtime_files.resolve_voice_reference_path


@dataclass(frozen=True, slots=True)
class ProductionVisualPlatform:
    """Complete Visual Reply capabilities supplied by the visual owner."""

    capabilities: VisualCapabilities
    request_id_factory: Callable[[], str]


@dataclass(frozen=True, slots=True)
class ProductionSensoryPlatform:
    """Sensory effects plus the process-owned source registry."""

    capabilities: SensoryCapabilities
    registry: object | None = None


@dataclass(frozen=True, slots=True)
class ProductionInteractionPlatform:
    """Manual/hotkey interaction policy with core-owned hotkey adapters."""

    check_barge_in: Callable[[object], bool]
    dry_run_active: Callable[[], bool]
    push_to_talk_gui_held: Callable[[], bool]
    queue_size: int = 32
    is_hotkey_pressed: Callable[[str], bool] = runtime_hotkeys.is_hotkey_binding_pressed
    bind_hotkeys: Callable[[], object] = runtime_hotkeys.bind_hotkey_state_tracker
    unbind_hotkeys: Callable[[], object] = runtime_hotkeys.unbind_hotkey_state_tracker
    logger: Callable[[str], None] = print

    def capabilities(self) -> InteractionCapabilities:
        for name in (
            "check_barge_in",
            "dry_run_active",
            "push_to_talk_gui_held",
            "is_hotkey_pressed",
            "bind_hotkeys",
            "unbind_hotkeys",
            "logger",
        ):
            _require_callable(f"interaction.{name}", getattr(self, name))
        return InteractionCapabilities(
            is_hotkey_pressed=self.is_hotkey_pressed,
            bind_hotkeys=self.bind_hotkeys,
            unbind_hotkeys=self.unbind_hotkeys,
            dry_run_active=self.dry_run_active,
            push_to_talk_gui_held=self.push_to_talk_gui_held,
            check_barge_in=self.check_barge_in,
            logger=self.logger,
        )


@dataclass(frozen=True, slots=True)
class ProductionRealtimePlatformInputs:
    """All finite platform edges needed to construct realtime ownership."""

    speech_input: ProductionSpeechInputPlatform
    tts: ProductionTtsPlatform
    playback: ProductionPlaybackPlatform
    replay: ProductionReplayPlatform
    visual: ProductionVisualPlatform
    sensory: ProductionSensoryPlatform
    interaction: ProductionInteractionPlatform


def build_production_realtime_platform(
    inputs: ProductionRealtimePlatformInputs,
) -> ProductionRealtimeOwners:
    """Construct realtime owners without engine or UI reach-through."""

    if not isinstance(inputs, ProductionRealtimePlatformInputs):
        raise TypeError("inputs must be ProductionRealtimePlatformInputs")
    if not isinstance(inputs.tts.events, ProductionTtsEvents):
        raise TypeError("tts.events must be ProductionTtsEvents")
    if inputs.playback.events is not inputs.tts.events:
        raise ValueError("TTS and playback must share one ProductionTtsEvents owner")
    if inputs.replay.events is not inputs.tts.events:
        raise ValueError("TTS and replay must share one ProductionTtsEvents owner")
    for name, value in (
        ("tts.adapter_for", inputs.tts.adapter_for),
        ("tts.logger", inputs.tts.logger),
        ("playback.volume_for", inputs.playback.volume_for),
        ("playback.play_file", inputs.playback.play_file),
        ("playback.delete_audio", inputs.playback.delete_audio),
        ("replay.resolve_voice", inputs.replay.resolve_voice),
        ("visual.request_id_factory", inputs.visual.request_id_factory),
    ):
        _require_callable(name, value)
    if not isinstance(inputs.visual.capabilities, VisualCapabilities):
        raise TypeError("visual.capabilities must be VisualCapabilities")
    if not isinstance(inputs.sensory.capabilities, SensoryCapabilities):
        raise TypeError("sensory.capabilities must be SensoryCapabilities")

    events = inputs.tts.events
    return build_production_realtime_owners(
        speech_input_owner=ProductionSpeechInputOwner(
            capabilities=inputs.speech_input.capabilities(),
            tuning=inputs.speech_input.tuning,
            logger=inputs.speech_input.logger,
        ),
        tts_owner=ProductionTtsOwner(
            adapter_for=inputs.tts.adapter_for,
            sentence_splitter=inputs.tts.sentence_splitter,
            events=events,
            set_seed=inputs.tts.set_seed,
            logger=inputs.tts.logger,
            prepare_playback_audio=inputs.tts.prepare_playback_audio,
            incremental_pcm_allowed=inputs.tts.incremental_pcm_allowed,
        ),
        playback_owner=ProductionPlaybackOwner(
            play_file=inputs.playback.play_file,
            delete_audio=inputs.playback.delete_audio,
            volume_for=inputs.playback.volume_for,
            events=events,
            supports_audio_start=inputs.playback.supports_audio_start,
            open_local_session=inputs.playback.open_local_session,
        ),
        replay_owner=ProductionReplayOwner(
            resolve_voice=inputs.replay.resolve_voice,
            events=events,
        ),
        visual_owner=ProductionVisualOwner(
            capabilities=inputs.visual.capabilities,
            request_id_factory=inputs.visual.request_id_factory,
        ),
        sensory_owner=ProductionSensoryOwner(
            capabilities=inputs.sensory.capabilities,
            registry=(
                inputs.sensory.registry
                if inputs.sensory.registry is not None
                else sensory.get_registry()
            ),
        ),
        interaction_owner=ProductionInteractionOwner(
            capabilities=inputs.interaction.capabilities(),
            queue_size=inputs.interaction.queue_size,
        ),
    )


__all__ = [
    "ProductionInteractionPlatform",
    "ProductionPlaybackPlatform",
    "ProductionRealtimePlatformInputs",
    "ProductionReplayPlatform",
    "ProductionSensoryPlatform",
    "ProductionSpeechInputPlatform",
    "ProductionTtsPlatform",
    "ProductionVisualPlatform",
    "build_production_realtime_platform",
]
