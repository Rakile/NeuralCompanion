"""Finite process ports for concrete desktop realtime composition.

This module translates explicit process-owned resources into
``ProductionDesktopRealtimeInputs``.  The few owners constructed after the
runtime foundation use narrow one-owner bindings; no callback locates an
engine, UI shell, runtime context, or generic service registry.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.runtime.production_desktop_realtime import (
    DesktopAddonCapabilityPort,
    DesktopRuntimeConfigSource,
    DesktopSpeechBackendOwner,
    DesktopVisualReplyCapabilities,
    ProductionDesktopInteractionInputs,
    ProductionDesktopPlaybackInputs,
    ProductionDesktopRealtimeInputs,
    ProductionDesktopSensoryInputs,
    ProductionDesktopSpeechInputs,
    ProductionDesktopTtsInputs,
    ProductionDesktopVisualInputs,
)
from core.runtime.production_realtime import PreparedSentenceSplitterOwner
from core.runtime.speech_input import SpeechInputTuning


class DesktopEventState(Protocol):
    def set(self) -> object: ...

    def clear(self) -> object: ...

    def is_set(self) -> bool: ...


class DesktopDryRunPolicy(Protocol):
    def dry_run_auto_replies_enabled(self) -> bool: ...


class DesktopSeedOwner(Protocol):
    def set_seed(self, seed: int) -> object: ...


class DesktopVisualHistoryOwner(Protocol):
    def attach_history(self, link: object) -> object: ...

    def refresh_history(self, lease: object) -> object: ...


class DesktopSensoryOwner(Protocol):
    """Finite effect and policy surface consumed by ``SensoryService``."""

    def orb_focus(self, payload: Mapping[str, object], lease: object) -> object: ...

    def avatar_emotion(self, emotion: str, lease: object) -> object: ...

    def proactive(self, payload: Mapping[str, object], lease: object) -> object: ...

    def visual(
        self,
        payload: Mapping[str, object],
        lease: object,
        config: object,
    ) -> object: ...

    def publish_event(
        self,
        name: str,
        payload: Mapping[str, object],
        lease: object,
    ) -> object: ...

    def request_chat_rebuild(self, lease: object) -> object: ...

    def debug(self, event: str, fields: Mapping[str, object]) -> object: ...

    def loop_ready(self) -> bool: ...

    def blocked_reasons(self, allow_audio_playback: bool) -> object: ...

    def build_messages(self, *args: object, **kwargs: object) -> object: ...

    def model_supports_images(self, config: object) -> bool: ...

    def emotion_allowed(self, emotion: str) -> bool: ...

    def visual_allowed(self, config: object) -> bool: ...

    def proactive_ready(self) -> bool: ...


class DesktopBargeInOwner(Protocol):
    def check_for_barge_in(
        self,
        source: object,
        *,
        energy_threshold: float,
    ) -> bool: ...


_SPEECH_BACKEND_METHODS = ("resolve_stt_backend", "current_tts_adapter")
_CONFIG_METHODS = ("snapshot",)
_ADDON_METHODS = (
    "invoke_capability",
    "invoke_all_capabilities",
    "record_latency_event",
)
_VISUAL_HISTORY_METHODS = ("attach_history", "refresh_history")
_SENSORY_METHODS = (
    "orb_focus",
    "avatar_emotion",
    "proactive",
    "visual",
    "publish_event",
    "request_chat_rebuild",
    "debug",
    "loop_ready",
    "blocked_reasons",
    "build_messages",
    "model_supports_images",
    "emotion_allowed",
    "visual_allowed",
    "proactive_ready",
)
_VISUAL_REPLY_METHODS = (
    "generate",
    "publish_requested",
    "publish_result",
    "publish_failure",
    "next_request_id",
    "mode",
    "enabled",
    "enabled_for",
    "generation_available",
    "generation_available_for",
    "story_mode_enabled",
    "story_max_images",
    "story_continuity_strength",
    "story_theme_prompts",
    "story_theme_enabled",
    "story_theme_suffix",
    "master_style_prompt",
    "master_style_suffix",
    "master_prompt_safety_suffix",
    "no_speech_bubbles_suffix",
    "apply_style_anchor",
    "story_style_guide_from_text",
    "story_prompt_from_text",
    "normalize_prompt_text",
    "strip_visual_reply_tail",
    "looks_like_visual_reply_tag_prefix",
    "extract_visual_reply_prompt",
)


def _require_methods(label: str, owner: object, names: tuple[str, ...]) -> None:
    missing = tuple(name for name in names if not callable(getattr(owner, name, None)))
    if missing:
        raise TypeError(
            f"{label} requires callable methods: " + ", ".join(missing)
        )


class _RequiredOwnerBinding:
    """Thread-safe, bind-once storage behind a finite public adapter."""

    __slots__ = ("_label", "_lock", "_methods", "_owner")

    def __init__(self, label: str, methods: tuple[str, ...]) -> None:
        self._label = str(label)
        self._methods = tuple(methods)
        self._lock = threading.Lock()
        self._owner: object | None = None

    def bind(self, owner: object) -> None:
        _require_methods(self._label, owner, self._methods)
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


class ProductionDesktopSpeechBackendBinding:
    """Bind the graph-owned speech backend owner after foundation creation."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop speech backends",
            _SPEECH_BACKEND_METHODS,
        )

    def bind(self, owner: DesktopSpeechBackendOwner) -> None:
        self._binding.bind(owner)

    def resolve_stt_backend(self, backend_id: str) -> object:
        owner = self._binding.owner()
        return owner.resolve_stt_backend(str(backend_id or ""))

    def current_tts_adapter(self, config: object = None) -> object | None:
        owner = self._binding.owner()
        return owner.current_tts_adapter(config)


class ProductionDesktopRuntimeConfigBinding:
    """Bind the live ``RuntimeConfigService`` without exposing its context."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop runtime config",
            _CONFIG_METHODS,
        )

    def bind(self, owner: DesktopRuntimeConfigSource) -> None:
        self._binding.bind(owner)

    def snapshot(self) -> object:
        return self._binding.owner().snapshot()


class ProductionDesktopAddonCapabilityBinding:
    """Bind initialized addon dispatch directly, never through a getter."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop addon capabilities",
            _ADDON_METHODS,
        )

    def bind(self, owner: DesktopAddonCapabilityPort) -> None:
        self._binding.bind(owner)

    def invoke_capability(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        return self._binding.owner().invoke_capability(
            str(capability or ""),
            dict(payload or {}),
        )

    def invoke_all_capabilities(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> list[object]:
        return self._binding.owner().invoke_all_capabilities(
            str(capability or ""),
            dict(payload or {}),
        )

    def record_latency_event(self, event: str, **fields: object) -> object:
        return self._binding.owner().record_latency_event(
            str(event or ""),
            **dict(fields),
        )


class ProductionDesktopVisualHistoryBinding:
    """Bind history mutation only after conversation ownership exists."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop visual history",
            _VISUAL_HISTORY_METHODS,
        )

    def bind(self, owner: DesktopVisualHistoryOwner) -> None:
        self._binding.bind(owner)

    def attach_history(self, link: object) -> object:
        return self._binding.owner().attach_history(link)

    def refresh_history(self, lease: object) -> object:
        return self._binding.owner().refresh_history(lease)


class ProductionDesktopSensoryBinding:
    """Bind the completed sensory effects and policy owner as one finite port."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop sensory owner",
            _SENSORY_METHODS,
        )

    def bind(self, owner: DesktopSensoryOwner) -> None:
        self._binding.bind(owner)

    def orb_focus(self, payload, lease):
        return self._binding.owner().orb_focus(payload, lease)

    def avatar_emotion(self, emotion, lease):
        return self._binding.owner().avatar_emotion(str(emotion or ""), lease)

    def proactive(self, payload, lease):
        return self._binding.owner().proactive(payload, lease)

    def visual(self, payload, lease, config):
        return self._binding.owner().visual(payload, lease, config)

    def publish_event(self, name, payload, lease):
        return self._binding.owner().publish_event(str(name or ""), payload, lease)

    def request_chat_rebuild(self, lease):
        return self._binding.owner().request_chat_rebuild(lease)

    def debug(self, event, fields):
        return self._binding.owner().debug(str(event or ""), fields)

    def loop_ready(self) -> bool:
        return bool(self._binding.owner().loop_ready())

    def blocked_reasons(self, allow_audio_playback: bool) -> object:
        return self._binding.owner().blocked_reasons(bool(allow_audio_playback))

    def build_messages(self, *args: object, **kwargs: object) -> object:
        return self._binding.owner().build_messages(*args, **kwargs)

    def model_supports_images(self, config: object) -> bool:
        return bool(self._binding.owner().model_supports_images(config))

    def emotion_allowed(self, emotion: str) -> bool:
        return bool(self._binding.owner().emotion_allowed(str(emotion or "")))

    def visual_allowed(self, config: object) -> bool:
        return bool(self._binding.owner().visual_allowed(config))

    def proactive_ready(self) -> bool:
        return bool(self._binding.owner().proactive_ready())


class ProductionDesktopBargeInBinding:
    """Bind the runtime speech-input service used for barge-in sampling."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop barge-in owner",
            ("check_for_barge_in",),
        )

    def bind(self, owner: DesktopBargeInOwner) -> None:
        self._binding.bind(owner)

    def check_for_barge_in(
        self,
        source: object,
        *,
        energy_threshold: float,
    ) -> bool:
        return bool(
            self._binding.owner().check_for_barge_in(
                source,
                energy_threshold=float(energy_threshold),
            )
        )


class ProductionDesktopSeedBinding:
    """Bind the single graph-owned dry-run/seed authority after composition."""

    __slots__ = ("_binding",)

    def __init__(self) -> None:
        self._binding = _RequiredOwnerBinding(
            "Production desktop seed owner",
            ("set_seed",),
        )

    def bind(self, owner: DesktopSeedOwner) -> None:
        self._binding.bind(owner)

    def set_seed(self, seed: int) -> object:
        return self._binding.owner().set_seed(int(seed))


class ProductionDesktopEventBinding:
    """Bind one graph-owned event while retaining its event-shaped contract."""

    __slots__ = ("_binding",)

    def __init__(self, label: str) -> None:
        self._binding = _RequiredOwnerBinding(
            str(label),
            ("set", "clear", "is_set"),
        )

    def bind(self, event: DesktopEventState) -> None:
        self._binding.bind(event)

    def set(self) -> object:
        return self._binding.owner().set()

    def clear(self) -> object:
        return self._binding.owner().clear()

    def is_set(self) -> bool:
        return bool(self._binding.owner().is_set())


@dataclass(frozen=True, slots=True)
class ProductionDesktopControlEventBindings:
    """Late-bind graph control events needed by pre-graph process adapters."""

    stop_requested: ProductionDesktopEventBinding
    audio_playing: ProductionDesktopEventBinding
    microphone_active: ProductionDesktopEventBinding

    @classmethod
    def create(cls) -> "ProductionDesktopControlEventBindings":
        return cls(
            stop_requested=ProductionDesktopEventBinding(
                "Production desktop stop event"
            ),
            audio_playing=ProductionDesktopEventBinding(
                "Production desktop audio-playing event"
            ),
            microphone_active=ProductionDesktopEventBinding(
                "Production desktop microphone event"
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopRealtimeBindings:
    """The finite graph-cycle ports retained by the outer composition root."""

    speech_backends: ProductionDesktopSpeechBackendBinding
    config: ProductionDesktopRuntimeConfigBinding
    addons: ProductionDesktopAddonCapabilityBinding
    visual_history: ProductionDesktopVisualHistoryBinding
    sensory: ProductionDesktopSensoryBinding
    barge_in: ProductionDesktopBargeInBinding
    seed: ProductionDesktopSeedBinding
    control_events: ProductionDesktopControlEventBindings

    @classmethod
    def create(cls) -> "ProductionDesktopRealtimeBindings":
        return cls(
            speech_backends=ProductionDesktopSpeechBackendBinding(),
            config=ProductionDesktopRuntimeConfigBinding(),
            addons=ProductionDesktopAddonCapabilityBinding(),
            visual_history=ProductionDesktopVisualHistoryBinding(),
            sensory=ProductionDesktopSensoryBinding(),
            barge_in=ProductionDesktopBargeInBinding(),
            seed=ProductionDesktopSeedBinding(),
            control_events=ProductionDesktopControlEventBindings.create(),
        )


class ProductionDesktopPushToTalkAdapter:
    """Preserve physical/GUI PTT behavior and dry-run suppression."""

    __slots__ = ("_dry_run", "_gui_hold", "_physical_pressed")

    def __init__(
        self,
        *,
        dry_run: DesktopDryRunPolicy,
        gui_hold: DesktopEventState,
        physical_pressed: Callable[[], bool],
    ) -> None:
        _require_methods(
            "Desktop dry-run policy",
            dry_run,
            ("dry_run_auto_replies_enabled",),
        )
        _require_methods("Desktop GUI PTT event", gui_hold, ("set", "clear", "is_set"))
        if not callable(physical_pressed):
            raise TypeError("Desktop physical PTT check must be callable.")
        self._dry_run = dry_run
        self._gui_hold = gui_hold
        self._physical_pressed = physical_pressed

    def held(self) -> bool:
        if self._dry_run.dry_run_auto_replies_enabled():
            return False
        return bool(self._gui_hold.is_set() or self._physical_pressed())

    def gui_held(self) -> bool:
        return bool(self._gui_hold.is_set())

    def set_hold(self, active: bool) -> None:
        if self._dry_run.dry_run_auto_replies_enabled() or not bool(active):
            self._gui_hold.clear()
            return
        self._gui_hold.set()


class ProductionDesktopInteractionAdapter:
    """Use runtime speech-input barge-in with the configured desktop threshold."""

    __slots__ = ("_barge_in", "_dry_run", "_push_to_talk", "_threshold")

    def __init__(
        self,
        *,
        dry_run: DesktopDryRunPolicy,
        push_to_talk: ProductionDesktopPushToTalkAdapter,
        barge_in: DesktopBargeInOwner,
        energy_threshold: float,
    ) -> None:
        _require_methods(
            "Desktop dry-run policy",
            dry_run,
            ("dry_run_auto_replies_enabled",),
        )
        _require_methods(
            "Desktop push-to-talk adapter",
            push_to_talk,
            ("gui_held",),
        )
        _require_methods(
            "Desktop barge-in owner",
            barge_in,
            ("check_for_barge_in",),
        )
        self._dry_run = dry_run
        self._push_to_talk = push_to_talk
        self._barge_in = barge_in
        self._threshold = float(energy_threshold)

    def dry_run_active(self) -> bool:
        return bool(self._dry_run.dry_run_auto_replies_enabled())

    def push_to_talk_gui_held(self) -> bool:
        return self._push_to_talk.gui_held()

    def check_barge_in(self, source: object) -> bool:
        return bool(
            self._barge_in.check_for_barge_in(
                source,
                energy_threshold=self._threshold,
            )
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopSpeechPorts:
    recognizer: object
    speech_module: object
    np_module: object
    microphone_active: DesktopEventState
    push_to_talk: ProductionDesktopPushToTalkAdapter
    tuning: SpeechInputTuning
    pcm_callback: Callable[[bytes, int, int], object] | None = None

    def inputs(self) -> ProductionDesktopSpeechInputs:
        return ProductionDesktopSpeechInputs(
            recognizer=self.recognizer,
            speech_module=self.speech_module,
            np_module=self.np_module,
            microphone_active=self.microphone_active,
            push_to_talk_held=self.push_to_talk.held,
            set_push_to_talk_hold=self.push_to_talk.set_hold,
            tuning=self.tuning,
            pcm_callback=self.pcm_callback,
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopTtsPorts:
    sentence_splitter: PreparedSentenceSplitterOwner
    config: DesktopRuntimeConfigSource
    seed: DesktopSeedOwner

    def inputs(self) -> ProductionDesktopTtsInputs:
        _require_methods("Desktop sentence tokenizer", self.sentence_splitter, ("prepare", "splitter"))
        _require_methods("Desktop runtime config", self.config, _CONFIG_METHODS)
        _require_methods("Desktop seed owner", self.seed, ("set_seed",))
        return ProductionDesktopTtsInputs(
            sentence_splitter=self.sentence_splitter,
            config=self.config,
            set_seed=self.seed.set_seed,
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopPlaybackPorts:
    soundfile_module: object
    sounddevice_module: object
    audio_playing: DesktopEventState
    level_callback: Callable[[float], object] | None = None
    analysis_callback: Callable[[object], object] | None = None
    analysis_state: object | None = None
    state_callback: Callable[[str], object] | None = None

    def inputs(self) -> ProductionDesktopPlaybackInputs:
        _require_methods("Desktop soundfile module", self.soundfile_module, ("read",))
        _require_methods(
            "Desktop sounddevice module",
            self.sounddevice_module,
            ("play", "stop", "get_stream", "query_devices"),
        )
        _require_methods(
            "Desktop audio-playing event",
            self.audio_playing,
            ("set", "clear", "is_set"),
        )
        return ProductionDesktopPlaybackInputs(
            soundfile_module=self.soundfile_module,
            sounddevice_module=self.sounddevice_module,
            audio_playing=self.audio_playing,
            level_callback=self.level_callback,
            analysis_callback=self.analysis_callback,
            analysis_state=self.analysis_state,
            state_callback=self.state_callback,
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopVisualPorts:
    addon: DesktopVisualReplyCapabilities
    history: DesktopVisualHistoryOwner

    def inputs(self) -> ProductionDesktopVisualInputs:
        _require_methods("Visual Reply addon capabilities", self.addon, _VISUAL_REPLY_METHODS)
        _require_methods("Desktop visual history", self.history, _VISUAL_HISTORY_METHODS)
        return ProductionDesktopVisualInputs(
            addon=self.addon,
            attach_history=self.history.attach_history,
            refresh_history=self.history.refresh_history,
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopSensoryPorts:
    owner: DesktopSensoryOwner

    def inputs(self) -> ProductionDesktopSensoryInputs:
        _require_methods("Desktop sensory owner", self.owner, _SENSORY_METHODS)
        owner = self.owner
        return ProductionDesktopSensoryInputs(
            orb_focus=owner.orb_focus,
            avatar_emotion=owner.avatar_emotion,
            proactive=owner.proactive,
            visual=owner.visual,
            publish_event=owner.publish_event,
            request_chat_rebuild=owner.request_chat_rebuild,
            debug=owner.debug,
            loop_ready=owner.loop_ready,
            blocked_reasons=owner.blocked_reasons,
            build_messages=owner.build_messages,
            model_supports_images=owner.model_supports_images,
            emotion_allowed=owner.emotion_allowed,
            visual_allowed=owner.visual_allowed,
            proactive_ready=owner.proactive_ready,
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopInteractionPorts:
    policy: ProductionDesktopInteractionAdapter
    queue_size: int

    def inputs(self) -> ProductionDesktopInteractionInputs:
        _require_methods(
            "Desktop interaction policy",
            self.policy,
            ("dry_run_active", "push_to_talk_gui_held", "check_barge_in"),
        )
        return ProductionDesktopInteractionInputs(
            dry_run_active=self.policy.dry_run_active,
            push_to_talk_gui_held=self.policy.push_to_talk_gui_held,
            check_barge_in=self.policy.check_barge_in,
            queue_size=int(self.queue_size),
        )


@dataclass(frozen=True, slots=True)
class ProductionDesktopRealtimePorts:
    """All explicit outer-root resources needed by desktop realtime."""

    app_root: str | Path
    speech_backends: DesktopSpeechBackendOwner
    addons: DesktopAddonCapabilityPort
    speech: ProductionDesktopSpeechPorts
    tts: ProductionDesktopTtsPorts
    playback: ProductionDesktopPlaybackPorts
    visual: ProductionDesktopVisualPorts
    sensory: ProductionDesktopSensoryPorts
    interaction: ProductionDesktopInteractionPorts
    logger: Callable[[str], object]


def build_production_desktop_realtime_inputs(
    ports: ProductionDesktopRealtimePorts,
) -> ProductionDesktopRealtimeInputs:
    """Translate finite owners into the existing desktop composition record."""

    if not isinstance(ports, ProductionDesktopRealtimePorts):
        raise TypeError("ports must be ProductionDesktopRealtimePorts")
    if not isinstance(ports.app_root, (str, Path)) or not str(ports.app_root).strip():
        raise TypeError("Desktop realtime app_root must be a non-empty path.")
    _require_methods("Desktop speech backends", ports.speech_backends, _SPEECH_BACKEND_METHODS)
    _require_methods("Desktop addon capabilities", ports.addons, _ADDON_METHODS)
    if not callable(ports.logger):
        raise TypeError("Desktop realtime logger must be callable.")
    for label, value, expected in (
        ("speech", ports.speech, ProductionDesktopSpeechPorts),
        ("tts", ports.tts, ProductionDesktopTtsPorts),
        ("playback", ports.playback, ProductionDesktopPlaybackPorts),
        ("visual", ports.visual, ProductionDesktopVisualPorts),
        ("sensory", ports.sensory, ProductionDesktopSensoryPorts),
        ("interaction", ports.interaction, ProductionDesktopInteractionPorts),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"Desktop realtime {label} must be {expected.__name__}.")
    speech = ports.speech.inputs()
    if speech.recognizer is None:
        raise TypeError("Desktop speech recognizer is required.")
    if speech.speech_module is None or speech.np_module is None:
        raise TypeError("Desktop speech and numpy modules are required.")
    _require_methods("Desktop microphone event", speech.microphone_active, ("set", "clear", "is_set"))
    if not isinstance(speech.tuning, SpeechInputTuning):
        raise TypeError("Desktop speech tuning must be SpeechInputTuning.")
    return ProductionDesktopRealtimeInputs(
        app_root=ports.app_root,
        speech_backends=ports.speech_backends,
        addons=ports.addons,
        speech=speech,
        tts=ports.tts.inputs(),
        playback=ports.playback.inputs(),
        visual=ports.visual.inputs(),
        sensory=ports.sensory.inputs(),
        interaction=ports.interaction.inputs(),
        logger=ports.logger,
    )


__all__ = [
    "DesktopBargeInOwner",
    "DesktopDryRunPolicy",
    "DesktopEventState",
    "DesktopSeedOwner",
    "DesktopSensoryOwner",
    "DesktopVisualHistoryOwner",
    "ProductionDesktopAddonCapabilityBinding",
    "ProductionDesktopBargeInBinding",
    "ProductionDesktopControlEventBindings",
    "ProductionDesktopEventBinding",
    "ProductionDesktopInteractionAdapter",
    "ProductionDesktopInteractionPorts",
    "ProductionDesktopPlaybackPorts",
    "ProductionDesktopPushToTalkAdapter",
    "ProductionDesktopRealtimeBindings",
    "ProductionDesktopRealtimePorts",
    "ProductionDesktopRuntimeConfigBinding",
    "ProductionDesktopSeedBinding",
    "ProductionDesktopSensoryBinding",
    "ProductionDesktopSensoryPorts",
    "ProductionDesktopSpeechBackendBinding",
    "ProductionDesktopSpeechPorts",
    "ProductionDesktopTtsPorts",
    "ProductionDesktopVisualHistoryBinding",
    "ProductionDesktopVisualPorts",
    "build_production_desktop_realtime_inputs",
]
