"""Real process root for the production NeuralCompanion desktop runtime."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path

import nltk
import numpy as np
import speech_recognition as sr
import sounddevice as sd
import soundfile as sf

from core import audio_playback, avatar_hand_state, runtime_hotkeys
from core.runtime.context import RuntimeContext
from core.runtime.conversation_addons import ConversationAddonBinding
from core.runtime.contracts import CommandResult
from core.runtime.facade import ApplicationFacade
from core.runtime.production_composer import ProductionApplicationBindingEdges
from core.runtime.production_desktop_addon_ports import (
    ProductionDesktopAddonManagerPort,
    ProductionDesktopAvatarRegistryPort,
    ProductionDesktopMuseTalkRuntimePort,
)
from core.runtime.production_desktop_bootstrap import (
    ProductionDesktopApplicationBootstrap,
    ProductionDesktopBootstrapInputs,
    build_production_desktop_bootstrap,
)
from core.runtime.production_desktop_compatibility_ports import (
    ProductionDesktopCompatibilityPorts,
    ProductionDesktopNormalChatBlocked,
)
from core.runtime.production_desktop_graph_ports import (
    ProductionDesktopGraphPortBindings,
    build_production_desktop_graph_ports,
)
from core.runtime.production_desktop_identity import request_json
from core.runtime.production_desktop_realtime_ports import (
    ProductionDesktopInteractionAdapter,
    ProductionDesktopInteractionPorts,
    ProductionDesktopPlaybackPorts,
    ProductionDesktopPushToTalkAdapter,
    ProductionDesktopRealtimeBindings,
    ProductionDesktopRealtimePorts,
    ProductionDesktopSensoryPorts,
    ProductionDesktopSpeechPorts,
    ProductionDesktopTtsPorts,
    ProductionDesktopVisualPorts,
)
from core.runtime.production_defaults import build_production_runtime_defaults
from core.runtime.production_environment import ProductionSentenceTokenizer
from core.runtime.production_visual import ProductionVisualReplyPublicationGate
from core.runtime.speech_input import SpeechInputTuning
from visual_presence.microphone_analysis import MicrophonePresenceAnalyzer


_APP_ROOT = Path(__file__).resolve().parents[2]


class ProductionDesktopProcess:
    """Own one lazily composed desktop bootstrap for the current process."""

    __slots__ = ("_application", "_lock")

    def __init__(self) -> None:
        self._application: ProductionDesktopApplicationBootstrap | None = None
        self._lock = threading.Lock()

    def application(self) -> ProductionDesktopApplicationBootstrap:
        current = self._application
        if current is not None:
            return current
        with self._lock:
            current = self._application
            if current is None:
                current = _compose_desktop_application()
                self._application = current
            return current

    def context(self) -> RuntimeContext:
        return self.application().bootstrap.context()

    def facade(self) -> ApplicationFacade:
        return self.application().bootstrap.host().facade

    def run(
        self,
        config_override: Mapping[str, object] | None = None,
    ) -> CommandResult[None]:
        return self.application().bootstrap.run(config_override)

    def request_shutdown(self, reason: str = "user") -> None:
        self.application().bootstrap.request_shutdown(reason)


_PROCESS = ProductionDesktopProcess()


def get_runtime_context() -> RuntimeContext:
    return _PROCESS.context()


def get_application_facade() -> ApplicationFacade:
    return _PROCESS.facade()


def run_companion(
    config_override: Mapping[str, object] | None = None,
) -> CommandResult[None]:
    return _PROCESS.run(config_override)


def request_shutdown(reason: str = "user") -> None:
    _PROCESS.request_shutdown(reason)


def _compose_desktop_application() -> ProductionDesktopApplicationBootstrap:
    realtime_bindings = ProductionDesktopRealtimeBindings.create()
    publication_gate = ProductionVisualReplyPublicationGate(
        stop_requested=realtime_bindings.control_events.stop_requested,
        audio_playing=realtime_bindings.control_events.audio_playing,
    )
    defaults = build_production_runtime_defaults(
        _APP_ROOT,
        before_visual_reply_publish=publication_gate.allow,
    )
    visual_reply = defaults.visual_reply_capabilities
    if visual_reply is None:
        raise RuntimeError("Visual Reply production capabilities are unavailable.")

    addon_manager = ProductionDesktopAddonManagerPort()
    avatar_registry = ProductionDesktopAvatarRegistryPort(
        addon_manager.invoke_addon_capability
    )
    musetalk_runtime = ProductionDesktopMuseTalkRuntimePort(addon_manager)
    push_to_talk_gui_held = threading.Event()
    graph_ports = build_production_desktop_graph_ports(
        ProductionDesktopGraphPortBindings(
            avatar_addons=avatar_registry,
            conversation_addons=addon_manager,
            avatar_preview_state=musetalk_runtime,
            push_to_talk_held=push_to_talk_gui_held,
            # The legacy diagnostic switch was disabled by default.  The
            # concrete adapter remains finite and can be replaced by an
            # explicit diagnostics owner without changing graph contracts.
            log_musetalk_memory_checkpoint=lambda *_args, **_kwargs: None,
        )
    )

    def publish_presence_audio_level(level: float) -> None:
        """Fan out the playback meter to both registered presence surfaces."""

        try:
            numeric = max(0.0, min(1.0, float(level or 0.0)))
        except (TypeError, ValueError):
            numeric = 0.0
        for publish in (
            graph_ports.presence_visual.set_audio_level,
            graph_ports.presence_visual.set_companion_orb_audio_level,
        ):
            try:
                publish(numeric)
            except BaseException:
                # Audio-reactive visuals must never interrupt speech playback.
                pass

    def publish_presence_voice_analysis(frame: object) -> None:
        """Publish synchronized TTS features without affecting playback."""

        try:
            graph_ports.presence_visual.set_voice_analysis(frame)
        except BaseException:
            # Rich analysis is optional visual data and must fail silent.
            pass

    microphone_analyzer = MicrophonePresenceAnalyzer()
    microphone_analysis_lock = threading.Lock()
    microphone_analysis_enabled = False

    def publish_presence_microphone_pcm(
        data: bytes,
        sample_rate: int,
        sample_width: int,
    ) -> None:
        """Analyze PCM already consumed by STT; never open a second mic stream."""

        nonlocal microphone_analysis_enabled
        snapshot = realtime_bindings.config.snapshot()
        values = getattr(snapshot, "values", snapshot)
        enabled = bool(
            values.get("ai_presence_microphone_reactivity_enabled", False)
            if isinstance(values, Mapping)
            else False
        )
        if not enabled:
            should_clear = False
            with microphone_analysis_lock:
                if microphone_analysis_enabled:
                    microphone_analyzer.reset()
                    microphone_analysis_enabled = False
                    should_clear = True
            if should_clear:
                try:
                    graph_ports.presence_visual.set_user_voice_analysis(None, False)
                except BaseException:
                    pass
            return
        if not data:
            with microphone_analysis_lock:
                microphone_analyzer.reset()
                microphone_analysis_enabled = True
            try:
                graph_ports.presence_visual.set_user_voice_analysis(None, False)
            except BaseException:
                pass
            return
        try:
            with microphone_analysis_lock:
                microphone_analysis_enabled = True
                result = microphone_analyzer.analyze_pcm(
                    data,
                    sample_rate,
                    sample_width,
                )
            if result is not None:
                graph_ports.presence_visual.set_user_voice_analysis(
                    result.frame,
                    result.active,
                )
        except BaseException:
            # Microphone visualization must never delay or abort recognition.
            pass

    voice_analysis_state = audio_playback.VoiceAnalysisPlaybackState()

    def physical_push_to_talk_pressed() -> bool:
        snapshot = realtime_bindings.config.snapshot()
        values = getattr(snapshot, "values", snapshot)
        if not isinstance(values, Mapping):
            return False
        settings = runtime_hotkeys.normalize_hotkey_settings(
            values.get("hotkeys"),
            legacy_push_to_talk=values.get("push_to_talk_hotkey"),
            legacy_manual=values.get("manual_action_hotkeys"),
            legacy_ui=values.get("ui_action_hotkeys"),
        )
        return runtime_hotkeys.is_hotkey_binding_pressed(
            settings.get("push_to_talk", runtime_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY)
        )

    push_to_talk = ProductionDesktopPushToTalkAdapter(
        dry_run=graph_ports.dry_run,
        gui_hold=push_to_talk_gui_held,
        physical_pressed=physical_push_to_talk_pressed,
    )
    interaction = ProductionDesktopInteractionAdapter(
        dry_run=graph_ports.dry_run,
        push_to_talk=push_to_talk,
        barge_in=realtime_bindings.barge_in,
        energy_threshold=500.0,
    )
    realtime_ports = ProductionDesktopRealtimePorts(
        app_root=_APP_ROOT,
        speech_backends=realtime_bindings.speech_backends,
        addons=realtime_bindings.addons,
        speech=ProductionDesktopSpeechPorts(
            recognizer=sr.Recognizer(),
            speech_module=sr,
            np_module=np,
            microphone_active=realtime_bindings.control_events.microphone_active,
            push_to_talk=push_to_talk,
            tuning=SpeechInputTuning(
                energy_threshold=500.0,
                dynamic_energy_threshold=True,
                pause_threshold=2.2,
                non_speaking_duration=0.35,
                phrase_threshold=0.2,
                ambient_calibration_seconds=0.6,
                sample_rate=16000,
                push_to_talk_max_seconds=300.0,
                push_to_talk_tail_seconds=0.55,
                push_to_talk_min_tail_chunks=8,
                barge_in_reset_seconds=0.25,
                barge_in_consecutive_chunks=2,
            ),
            pcm_callback=publish_presence_microphone_pcm,
        ),
        tts=ProductionDesktopTtsPorts(
            sentence_splitter=ProductionSentenceTokenizer(nltk),
            config=realtime_bindings.config,
            seed=realtime_bindings.seed,
        ),
        playback=ProductionDesktopPlaybackPorts(
            soundfile_module=sf,
            sounddevice_module=sd,
            audio_playing=realtime_bindings.control_events.audio_playing,
            level_callback=publish_presence_audio_level,
            analysis_callback=publish_presence_voice_analysis,
            analysis_state=voice_analysis_state,
            state_callback=graph_ports.presence_visual.set_ai_state,
        ),
        visual=ProductionDesktopVisualPorts(
            visual_reply,
            realtime_bindings.visual_history,
        ),
        sensory=ProductionDesktopSensoryPorts(realtime_bindings.sensory),
        interaction=ProductionDesktopInteractionPorts(interaction, 32),
        logger=print,
    )
    compatibility_ports = ProductionDesktopCompatibilityPorts.create(
        blocked_error=ProductionDesktopNormalChatBlocked
    )
    return build_production_desktop_bootstrap(
        ProductionDesktopBootstrapInputs(
            app_root=_APP_ROOT,
            defaults=defaults,
            realtime_ports=realtime_ports,
            realtime_bindings=realtime_bindings,
            addon_manager=addon_manager,
            graph_ports=graph_ports,
            compatibility_ports=compatibility_ports,
            binding_edges=ProductionApplicationBindingEdges(),
            conversation_addon_binding=ConversationAddonBinding(),
            avatar_hand_debug=avatar_hand_state.HAND_DEBUG,
            identity_request_json=request_json,
            memory_embedding_request_json=request_json,
            logger=print,
        )
    )


__all__ = [
    "ProductionDesktopProcess",
    "get_application_facade",
    "get_runtime_context",
    "request_shutdown",
    "run_companion",
]
