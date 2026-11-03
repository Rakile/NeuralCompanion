"""Concrete desktop composition for production realtime ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Protocol

from core import audio_playback, runtime_files, runtime_hotkeys, sensory
from core.musetalk_timing import start_musetalk_timing
from core.runtime.production_realtime import (
    PreparedSentenceSplitterOwner,
    ProductionRealtimeOwners,
    ProductionTtsEvents,
)
from core.runtime.production_realtime_platform import (
    ProductionInteractionPlatform,
    ProductionPlaybackPlatform,
    ProductionRealtimePlatformInputs,
    ProductionReplayPlatform,
    ProductionSensoryPlatform,
    ProductionSpeechInputPlatform,
    ProductionTtsPlatform,
    ProductionVisualPlatform,
    build_production_realtime_platform,
)
from core.runtime.sensory import SensoryCapabilities
from core.runtime.speech_input import SpeechInputTuning
from core.runtime.visual import VisualCapabilities, VisualPolicyCapabilities


class DesktopSpeechBackendOwner(Protocol):
    """Late-bound speech backend ownership used by the desktop process."""

    def resolve_stt_backend(self, backend_id: str) -> object: ...

    def current_tts_adapter(self, config: object = None) -> object | None: ...


class DesktopRuntimeConfigSource(Protocol):
    """Read the current runtime configuration without locating the engine."""

    def snapshot(self) -> object: ...


class DesktopAddonCapabilityPort(Protocol):
    """Initialized-addon dispatch and latency diagnostics used by realtime."""

    def invoke_capability(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> object: ...

    def invoke_all_capabilities(
        self,
        capability: str,
        payload: dict[str, object] | None = None,
    ) -> list[object]: ...

    def record_latency_event(self, event: str, **fields: object) -> object: ...


class DesktopVisualReplyCapabilities(Protocol):
    """Non-UI capability object declared by the Visual Reply addon."""

    def generate(self, request: object, token: object) -> object: ...

    def publish_requested(self, request: object) -> object: ...

    def publish_result(self, result: object) -> object: ...

    def publish_failure(self, request: object, failure: object) -> object: ...

    def next_request_id(self) -> str: ...

    def mode(self) -> str: ...

    def enabled(self) -> bool: ...

    def enabled_for(self, config: Mapping[str, object]) -> bool: ...

    def generation_available(self) -> bool: ...

    def generation_available_for(self, config: Mapping[str, object]) -> bool: ...

    def story_mode_enabled(self) -> bool: ...

    def story_max_images(self) -> int: ...

    def story_continuity_strength(self) -> float: ...

    def story_theme_prompts(self) -> Mapping[str, str]: ...

    def story_theme_enabled(self) -> tuple[str, ...] | list[str]: ...

    def story_theme_suffix(self) -> str: ...

    def master_style_prompt(self) -> str: ...

    def master_style_suffix(self) -> str: ...

    def master_prompt_safety_suffix(self) -> str: ...

    def no_speech_bubbles_suffix(self) -> str: ...

    def apply_style_anchor(self, prompt: str) -> str: ...

    def story_style_guide_from_text(
        self,
        text: str,
        continuity_strength: float,
    ) -> str: ...

    def story_prompt_from_text(
        self,
        prompt: str,
        emotion: str,
        story_style_guide: str,
    ) -> str: ...

    def normalize_prompt_text(self, prompt: str) -> str: ...

    def strip_visual_reply_tail(self, text: str) -> tuple[str, str]: ...

    def looks_like_visual_reply_tag_prefix(self, fragment: str) -> bool: ...

    def extract_visual_reply_prompt(self, text: str) -> tuple[str, str]: ...


@dataclass(frozen=True, slots=True)
class ProductionDesktopSpeechInputs:
    recognizer: object
    speech_module: object
    np_module: object
    microphone_active: object
    push_to_talk_held: Callable[[], bool]
    set_push_to_talk_hold: Callable[[bool], object]
    tuning: SpeechInputTuning
    pcm_callback: Callable[[bytes, int, int], object] | None = None


@dataclass(frozen=True, slots=True)
class ProductionDesktopTtsInputs:
    sentence_splitter: PreparedSentenceSplitterOwner
    config: DesktopRuntimeConfigSource
    set_seed: Callable[[int], object]


@dataclass(frozen=True, slots=True)
class ProductionDesktopPlaybackInputs:
    soundfile_module: object
    sounddevice_module: object
    audio_playing: object
    level_callback: Callable[[float], object] | None = None
    analysis_callback: Callable[[object], object] | None = None
    analysis_state: audio_playback.VoiceAnalysisPlaybackState | None = None
    state_callback: Callable[[str], object] | None = None


@dataclass(frozen=True, slots=True)
class ProductionDesktopVisualInputs:
    addon: DesktopVisualReplyCapabilities
    attach_history: Callable[[object], object]
    refresh_history: Callable[[object], object]


@dataclass(frozen=True, slots=True)
class ProductionDesktopSensoryInputs:
    orb_focus: Callable[[Mapping[str, object], object], object]
    avatar_emotion: Callable[[str, object], object]
    proactive: Callable[[Mapping[str, object], object], object]
    visual: Callable[[Mapping[str, object], object, object], object]
    publish_event: Callable[[str, Mapping[str, object], object], object]
    request_chat_rebuild: Callable[[object], object]
    debug: Callable[[str, Mapping[str, object]], object]
    loop_ready: Callable[[], bool]
    blocked_reasons: Callable[[bool], object]
    build_messages: Callable[..., object]
    model_supports_images: Callable[[object], bool]
    emotion_allowed: Callable[[str], bool]
    visual_allowed: Callable[[object], bool]
    proactive_ready: Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ProductionDesktopInteractionInputs:
    dry_run_active: Callable[[], bool]
    push_to_talk_gui_held: Callable[[], bool]
    check_barge_in: Callable[[object], bool]
    queue_size: int = 32


@dataclass(frozen=True, slots=True)
class ProductionDesktopRealtimeInputs:
    """Finite desktop leaves required before production foundation creation."""

    app_root: str | Path
    speech_backends: DesktopSpeechBackendOwner
    addons: DesktopAddonCapabilityPort
    speech: ProductionDesktopSpeechInputs
    tts: ProductionDesktopTtsInputs
    playback: ProductionDesktopPlaybackInputs
    visual: ProductionDesktopVisualInputs
    sensory: ProductionDesktopSensoryInputs
    interaction: ProductionDesktopInteractionInputs
    logger: Callable[[str], object] = print


_VISUAL_METHODS = (
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


def _callable_missing(owner: object, prefix: str, names: tuple[str, ...]) -> list[str]:
    return [
        f"{prefix}.{name}"
        for name in names
        if not callable(getattr(owner, name, None))
    ]


def _validate_inputs(inputs: ProductionDesktopRealtimeInputs) -> None:
    if not isinstance(inputs, ProductionDesktopRealtimeInputs):
        raise TypeError("inputs must be ProductionDesktopRealtimeInputs")
    for name, value, expected in (
        ("speech", inputs.speech, ProductionDesktopSpeechInputs),
        ("tts", inputs.tts, ProductionDesktopTtsInputs),
        ("visual", inputs.visual, ProductionDesktopVisualInputs),
        ("sensory", inputs.sensory, ProductionDesktopSensoryInputs),
        ("interaction", inputs.interaction, ProductionDesktopInteractionInputs),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"{name} must be {expected.__name__}")

    missing: list[str] = []
    if not isinstance(inputs.app_root, (str, Path)) or not str(inputs.app_root).strip():
        missing.append("app_root")
    if inputs.speech.recognizer is None:
        missing.append("speech.recognizer")
    if inputs.speech.speech_module is None:
        missing.append("speech.speech_module")
    if inputs.speech.np_module is None:
        missing.append("speech.np_module")
    if inputs.speech.microphone_active is None:
        missing.append("speech.microphone_active")
    if not isinstance(inputs.speech.tuning, SpeechInputTuning):
        missing.append("speech.tuning")
    missing.extend(
        _callable_missing(
            inputs.speech,
            "speech",
            ("push_to_talk_held", "set_push_to_talk_hold"),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.speech.microphone_active,
            "speech.microphone_active",
            ("set", "clear", "is_set"),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.speech.speech_module,
            "speech.speech_module",
            ("Microphone", "AudioData", "WaitTimeoutError", "UnknownValueError"),
        )
    )
    microphone = getattr(inputs.speech.speech_module, "Microphone", None)
    missing.extend(
        _callable_missing(
            microphone,
            "speech.speech_module.Microphone",
            ("list_microphone_names",),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.speech.np_module,
            "speech.np_module",
            ("frombuffer", "sqrt", "mean"),
        )
    )
    for name in ("int16", "int64"):
        if getattr(inputs.speech.np_module, name, None) is None:
            missing.append(f"speech.np_module.{name}")
    missing.extend(
        _callable_missing(
            inputs.speech_backends,
            "speech_backends",
            ("resolve_stt_backend", "current_tts_adapter"),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.addons,
            "addons",
            (
                "invoke_capability",
                "invoke_all_capabilities",
                "record_latency_event",
            ),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.tts.sentence_splitter,
            "tts.sentence_splitter",
            ("prepare", "splitter"),
        )
    )
    missing.extend(_callable_missing(inputs.tts.config, "tts.config", ("snapshot",)))
    missing.extend(_callable_missing(inputs.tts, "tts", ("set_seed",)))
    if inputs.visual.addon is None:
        missing.append("visual.addon")
    else:
        missing.extend(_callable_missing(inputs.visual.addon, "visual.addon", _VISUAL_METHODS))
    missing.extend(
        _callable_missing(
            inputs.visual,
            "visual",
            ("attach_history", "refresh_history"),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.sensory,
            "sensory",
            (
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
            ),
        )
    )
    missing.extend(
        _callable_missing(
            inputs.interaction,
            "interaction",
            ("dry_run_active", "push_to_talk_gui_held", "check_barge_in"),
        )
    )
    if not callable(inputs.logger):
        missing.append("logger")
    if missing:
        raise TypeError(
            "Missing required desktop realtime leaves: " + ", ".join(missing)
        )


def _estimate_tts_duration_seconds(text: str) -> float:
    """Return a bounded pacing estimate used only by conversation highlighting."""

    spoken = str(text or "").strip()
    if not spoken:
        return 0.0
    word_count = len(spoken.split())
    pause_count = sum(spoken.count(mark) for mark in ".,;:!?")
    return round(max(0.65, (word_count * 0.34) + (pause_count * 0.08)), 3)


def _playback_duration_seconds(text: str, value: object) -> float:
    """Prefer measured playback duration and retain the estimate as fallback."""

    try:
        measured = max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        measured = 0.0
    return measured if measured > 0.0 else _estimate_tts_duration_seconds(text)


class _ProductionDesktopTtsEvents:
    __slots__ = (
        "_addons",
        "_logger",
        "_pipeline_lock",
        "_pipeline_reply_id",
        "_pipeline_sources",
        "_pipeline_progressive_chunks",
    )

    def __init__(
        self,
        addons: DesktopAddonCapabilityPort,
        logger: Callable[[str], object],
    ) -> None:
        self._addons = addons
        self._logger = logger
        self._pipeline_lock = threading.Lock()
        self._pipeline_reply_id: object = None
        self._pipeline_sources: dict[int, str] = {}
        self._pipeline_progressive_chunks: set[int] = set()

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        return dict(value or {})

    def _invoke(self, capability: str, payload: object) -> object:
        try:
            return self._addons.invoke_capability(
                capability,
                self._payload(payload),
            )
        except Exception as exc:
            self._logger(f"[Addons] Capability '{capability}' failed: {exc}")
            return None

    def _invoke_all(self, capability: str, payload: object) -> list[object]:
        try:
            return list(
                self._addons.invoke_all_capabilities(
                    capability,
                    self._payload(payload),
                )
                or ()
            )
        except Exception as exc:
            self._logger(f"[Addons] Capability fanout '{capability}' failed: {exc}")
            return []

    def trace(self, event: str, fields: object) -> None:
        event_name = str(event or "")
        payload = dict(fields or {})
        try:
            self._addons.record_latency_event(event_name, **payload)
        except Exception:
            pass
        self._update_pipeline_telemetry(event_name, payload)

    def local_audio_progress(self, payload):
        # Numeric presentation only, never per-piece latency logs or PCM fanout.
        self._update_pipeline_telemetry("tts_local_audio_progress", payload)

    def _update_pipeline_telemetry(
        self,
        event: str,
        fields: Mapping[str, object],
    ) -> None:
        try:
            sequence = int(fields.get("sequence", 0) or 0)
        except (TypeError, ValueError):
            sequence = 0
        with self._pipeline_lock:
            if event == "tts_generation_start":
                engine_mode = str(fields.get("engine_mode", "") or "").lower()
                if engine_mode not in {"musetalk", "none", "scenic"}:
                    self._pipeline_reply_id = None
                    return
                if sequence == 0 or self._pipeline_reply_id is None:
                    self._pipeline_sources.clear()
                    self._pipeline_progressive_chunks.clear()
                    self._pipeline_reply_id = self._invoke(
                        "runtime.pipeline.begin",
                        {"stream_mode": bool(fields.get("streaming", False))},
                    )
                    if self._pipeline_reply_id is None:
                        return
                    self._invoke(
                        "runtime.pipeline.update_flags",
                        {
                            "reply_id": self._pipeline_reply_id,
                            "updates": {
                                "engine_mode": engine_mode,
                                "stream_open": bool(fields.get("streaming", False)),
                            },
                        },
                    )
                progressive = engine_mode == "musetalk" and fields.get("incremental_pcm") is True
                if progressive:
                    self._pipeline_progressive_chunks.add(sequence)
                text = str(fields.get("text", "") or "")
                self._pipeline_sources[sequence] = str(fields.get("speech_id") or "")
                self._update_pipeline_chunk(
                    sequence,
                    status="generating_audio",
                    playback_state="pending",
                    speech_session_generation=fields.get("speech_session_generation"),
                    speech_transaction_id=str(fields.get("speech_transaction_id") or ""),
                    speech_message_id=str(fields.get("speech_message_id") or ""),
                    speech_hidden=bool(fields.get("speech_hidden", False)),
                    **({"progressive_audio": True, "progressive_render_complete": False}
                       if progressive else {}),
                    **(
                        {
                            "text": text,
                            "duration_seconds": _estimate_tts_duration_seconds(text),
                        }
                        if text
                        else {}
                    ),
                )
                return
            if self._pipeline_reply_id is None:
                return
            progressive = sequence in self._pipeline_progressive_chunks
            if event == "tts_generation_cancelled":
                source = str(fields.get("speech_id") or "")
                if source and self._pipeline_sources.get(sequence) == source:
                    self._update_pipeline_chunk(sequence, status="cancelled", playback_state="cancelled")
                return
            if event == "tts_local_audio_progress":
                source = str(fields.get("speech_id") or "")
                if not source or self._pipeline_sources.get(sequence) != source:
                    return
                self._update_pipeline_chunk(sequence, **{key: fields[key] for key in (
                    "audio_media_seconds", "audio_clock_monotonic", "audio_scheduled_through_seconds",
                    "audio_clock_running", "duration_seconds", "audio_duration_estimated", "audio_progress_floor")
                    if key in fields})
                return
            if event in {"tts_generation", "tts_audio_file_saved"}:
                source = str(fields.get("speech_id") or "")
                if source and self._pipeline_sources.get(sequence) != source:
                    return
                outcome = fields.get("outcome")
                if outcome in {"cancelled", "error"}:
                    self._update_pipeline_chunk(sequence, status=outcome, playback_state=outcome)
                elif not progressive:
                    self._update_pipeline_chunk(sequence, status="rendered")
            elif event == "tts_chunk_playback_start":
                text = str(fields.get("text", "") or "")
                duration_seconds = _playback_duration_seconds(
                    text,
                    fields.get("duration_seconds", 0.0),
                )
                self._update_pipeline_chunk(
                    sequence,
                    playback_state="playing",
                    **({"status": "rendered"} if not progressive else {}),
                    audio_started_at=time.time(),
                    **(
                        {
                            "text": text,
                            "duration_seconds": duration_seconds,
                        }
                        if text
                        else {}
                    ),
                )
            elif event == "tts_chunk_playback_end":
                if fields.get("playback_reason", "completed") != "completed":
                    self._update_pipeline_chunk(sequence, status="cancelled", playback_state="cancelled")
                    return
                self._update_pipeline_chunk(
                    sequence,
                    status="rendered",
                    playback_state="completed",
                    duration_seconds=max(
                        0.0,
                        float(fields.get("duration_seconds", float(fields.get("duration_ms", 0.0) or 0.0) / 1000.0) or 0.0),
                    ),
                )

    def _update_pipeline_chunk(self, sequence: int, **updates: object) -> None:
        self._invoke(
            "runtime.pipeline.update_chunk",
            {
                "reply_id": self._pipeline_reply_id,
                "sequence_index": max(0, int(sequence)),
                "updates": dict(updates),
            },
        )

    def generation_started(self, payload: object) -> bool:
        return self._invoke("tts.generation_started", payload) is not None

    def generation_finished(self, payload: object) -> bool:
        return self._invoke("tts.generation_finished", payload) is not None

    def audio_chunk_ready(self, payload: object) -> dict[str, bool]:
        results = self._invoke_all("tts.audio_chunk_ready", payload)
        return {
            "handled": any(result is not None for result in results),
            **({"progressive_audio_admitted": True} if any(
                isinstance(result, Mapping) and result.get("progressive_audio_admitted") is True
                for result in results
            ) else {}),
            "skip_local_playback": any(
                isinstance(result, Mapping)
                and bool(result.get("skip_local_playback", False))
                for result in results
            ),
        }

    def segment_started(self, payload: object) -> bool:
        return self._invoke("tts.segment_started", payload) is not None

    def duck_start(self, payload: object) -> bool:
        return any(
            isinstance(result, Mapping) and bool(result.get("ducked", False))
            for result in self._invoke_all("tts.duck.start", payload)
        )

    def duck_end(self, payload: object) -> bool:
        return any(
            result is not None
            for result in self._invoke_all("tts.duck.end", payload)
        )


def _runtime_config_values(source: DesktopRuntimeConfigSource) -> Mapping[str, object]:
    snapshot = source.snapshot()
    values = getattr(snapshot, "values", snapshot)
    if not isinstance(values, Mapping):
        raise TypeError("tts.config snapshot must expose mapping values")
    return values


def _audio_analysis_fps(values: Mapping[str, object] | object) -> int:
    settings = values if isinstance(values, Mapping) else {}
    try:
        return max(
            5,
            min(120, int(settings.get("ai_presence_audio_refresh_hz", 30) or 30)),
        )
    except (TypeError, ValueError):
        return 30


def _normalized_voice_volume(value: object, fallback: object = 1.0) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        try:
            volume = float(fallback)
        except (TypeError, ValueError):
            volume = 1.0
    if volume > 2.0:
        volume /= 100.0
    return max(0.0, min(1.0, volume))


def _route_volume(route: object, fallback: object) -> float:
    values = route if isinstance(route, Mapping) else {}
    for key in ("volume", "voice_volume", "volume_percent", "voice_volume_percent"):
        if key in values:
            return _normalized_voice_volume(values.get(key), fallback)
    return _normalized_voice_volume(fallback)


def _playback_volume_for(
    inputs: ProductionDesktopRealtimeInputs,
    metadata: object,
    text: str,
) -> float:
    source = dict(metadata or {})
    fallback = _normalized_voice_volume(source.get("voice_volume", 1.0))
    config = _runtime_config_values(inputs.tts.config)
    master_volume = _normalized_voice_volume(
        config.get("audio_output_volume", 1.0),
        1.0,
    )
    payload = {
        "persona_id": str(source.get("persona_id", "") or ""),
        "text": str(text or ""),
        "tts_backend": str(config.get("tts_backend", "") or ""),
        "streaming": bool(config.get("stream_mode", False)),
    }
    try:
        routed = inputs.addons.invoke_capability("tts.voice_route", payload)
        if isinstance(routed, Mapping) and routed:
            return _route_volume(routed, fallback) * master_volume
    except Exception:
        pass
    route = source.get("voice_route")
    routed_volume = (
        _route_volume(route, fallback) if isinstance(route, Mapping) else fallback
    )
    return routed_volume * master_volume


def _selected_output_device(inputs: ProductionDesktopRealtimeInputs) -> int | None:
    config = _runtime_config_values(inputs.tts.config)
    label = str(
        config.get("audio_output_device", "Default Output") or "Default Output"
    ).strip()
    if not label or label.casefold() == "default output":
        return None
    try:
        devices = list(inputs.playback.sounddevice_module.query_devices() or ())
        outputs = [
            (index, str(device.get("name", "") or ""))
            for index, device in enumerate(devices)
            if int(device.get("max_output_channels", 0) or 0) > 0
        ]
        wanted = label.casefold()
        for index, name in outputs:
            if name.strip().casefold() == wanted:
                return index
        for index, name in outputs:
            candidate = name.strip().casefold()
            if wanted in candidate or candidate in wanted:
                return index
    except Exception as exc:
        inputs.logger(f"⚠️ Could not enumerate audio output devices: {exc}")
    inputs.logger(
        f"⚠️ Audio output device {label!r} was not found; using default output."
    )
    return None


def _incremental_pcm_allowed(inputs, chunk, config) -> bool:
    """Admit local No Avatar/Scenic/Ditto/MuseTalk audio; file consumers retain their route."""
    values = getattr(config, "values", {})
    if str(values.get("avatar_mode", "")).strip().lower() not in ('none', 'ditto', 'musetalk', 'scenic'):
        return False
    if not callable(getattr(inputs.playback.sounddevice_module, "OutputStream", None)):
        return False
    metadata = dict(getattr(chunk, "source_metadata", {}) or {})
    return not any(metadata.get(key) for key in (
        "publish_tts_addon_events", "remote_capture_id", "phone_reply_control", "skip_local_playback"))


def _prepare_incremental_playback_audio(inputs, chunk, values):
    from core.incremental_playback import IncrementalPlaybackAudio
    metadata = dict(getattr(chunk, "source_metadata", {}) or {})
    return IncrementalPlaybackAudio(chunk.audio_source,
        volume=_playback_volume_for(inputs, metadata, str(getattr(chunk, "text", ""))),
        level_callback=inputs.playback.level_callback,
        analysis_callback=inputs.playback.analysis_callback,
        level_fps=_audio_analysis_fps(values), logger=inputs.logger)


def _prepare_playback_audio(inputs: ProductionDesktopRealtimeInputs, chunk: object, config: object) -> object:
    values = getattr(config, "values", {})
    if getattr(chunk, "audio_source", None) is not None:
        return _prepare_incremental_playback_audio(inputs, chunk, values)
    if str(values.get("avatar_mode", "")).strip().lower() != "musetalk":
        return None
    metadata = dict(getattr(chunk, "source_metadata", {}) or {})
    if metadata.get("skip_local_playback", False):
        return None
    return audio_playback.prepare_audio_file(
        str(getattr(chunk, "audio_path", "")),
        soundfile_module=inputs.playback.soundfile_module,
        volume=_playback_volume_for(inputs, metadata, str(getattr(chunk, "text", ""))),
        level_callback=inputs.playback.level_callback,
        analysis_callback=inputs.playback.analysis_callback,
        level_fps=_audio_analysis_fps(values),
        logger=inputs.logger,
    )


def _play_audio_file(
    inputs: ProductionDesktopRealtimeInputs,
    path: str,
    *,
    stop_event: object,
    volume: float = 1.0,
    prepared_audio: object | None = None,
    on_started=None,
) -> object:
    state_callback = inputs.playback.state_callback
    if callable(state_callback):
        try:
            state_callback("speaking")
        except BaseException:
            pass
    try:
        output_device = _selected_output_device(inputs)
        trace_musetalk = False
        if start_musetalk_timing() is not None:
            try:
                trace_musetalk = str(
                    _runtime_config_values(inputs.tts.config).get("avatar_mode", "")
                ).strip().lower() == "musetalk"
            except Exception:
                # Optional diagnostics must not prevent otherwise valid audio.
                pass
        return audio_playback.play_audio_file(
            path,
            soundfile_module=inputs.playback.soundfile_module,
            sounddevice_module=inputs.playback.sounddevice_module,
            stop_event=stop_event,
            audio_playing_event=inputs.playback.audio_playing,
            output_device=output_device,
            volume=volume,
            level_callback=inputs.playback.level_callback,
            analysis_callback=inputs.playback.analysis_callback,
            analysis_state=inputs.playback.analysis_state,
            level_fps=_audio_analysis_fps(
                _runtime_config_values(inputs.tts.config)
            ),
            logger=inputs.logger,
            trace_musetalk=trace_musetalk,
            prepared_audio=prepared_audio,
            on_started=on_started,
        )
    finally:
        if callable(state_callback):
            try:
                state_callback("idle")
            except BaseException:
                pass


class _ContinuousDuckEffects:
    """One addon restore obligation, transferred across local output epochs.

    Addons expose a global start/end pair, not a reference count. Pending calls
    retain their obligation until the callback returns; foreign code never runs
    under this lock (and may synchronously replace or cancel its speech owner).
    """

    def __init__(self, events):
        self._events = events
        self._lock = threading.Lock()
        self._interval = None

    def start(self, owner, payload):
        with self._lock:
            if self._interval is not None:
                self._interval["owner"] = owner
                self._interval["start"] = payload
                return True  # Transfer active/pending restore responsibility.
            interval = {"owner": owner, "start": payload, "end": {}, "phase": "start"}
            self._interval = interval
        return self._transition(interval)

    def end(self, owner, payload):
        with self._lock:
            interval = self._interval
            if interval is None or interval["owner"] is not owner:
                return False
            interval["owner"], interval["end"] = None, payload
            if interval["phase"] != "active":
                return True  # The pending callback will complete/compensate.
            interval["phase"] = "end"
        self._transition(interval)
        return True

    def _transition(self, interval):
        first_result = None
        while True:
            with self._lock:
                phase = interval["phase"]
                payload = interval[phase]
            try:
                callback = self._events.duck_start if phase == "start" else self._events.duck_end
                result = bool(callback(payload))
            except BaseException:
                result = False
            if first_result is None:
                first_result = result
            with self._lock:
                if phase == "start":
                    if not result:
                        self._interval = None  # Never invent a restore after a declined/failed start.
                        return first_result
                    if interval["owner"] is not None:
                        interval["phase"] = "active"
                        return first_result
                    interval["phase"] = "end"  # Owner ended while start was pending.
                elif interval["owner"] is None:
                    self._interval = None
                    return first_result
                else:
                    interval["phase"] = "start"  # New speech arrived during the old restore.


def _open_local_session(inputs, events, owner, stop_event, selection):
    """Opt in for audio-only, Scenic and preflighted avatar routes on capable devices."""
    from core.continuous_audio import SoundDeviceSpeechSession
    from core.runtime.local_playback import LocalPlaybackSession
    from core.runtime.playback import AudioFilePlaybackCapabilities

    if not callable(getattr(inputs.playback.sounddevice_module, "OutputStream", None)):
        return None
    if selection[0] is not owner:
        config = _runtime_config_values(inputs.tts.config)
        if str(config.get("avatar_mode", "")).strip().lower() not in ("none", "musetalk", "ditto", "scenic"):
            return None
        selection[:2] = [owner, _selected_output_device(inputs)]
    if len(selection) == 2:
        selection.append(None)  # Shared audible-effects owner, including replacement epochs.
    if len(selection) == 3:
        selection.append(_ContinuousDuckEffects(events))
    duck_effects = selection[3]
    output_device = selection[1]
    playback = inputs.playback

    def prepare(chunk):
        if getattr(chunk, "audio_source", None) is not None:
            return _prepare_incremental_playback_audio(inputs, chunk, _runtime_config_values(inputs.tts.config))
        metadata = dict(getattr(chunk, "source_metadata", {}) or {})
        volume = _playback_volume_for(inputs, metadata, str(getattr(chunk, "text", "")))
        audio = getattr(chunk, "playback_audio", None)
        analysis_fps = _audio_analysis_fps(
            _runtime_config_values(inputs.tts.config)
        )
        if audio_playback._prepared_audio_is_compatible(
                audio, volume, playback.level_callback, playback.analysis_callback,
                analysis_fps):
            return audio
        return audio_playback.prepare_audio_file(chunk.audio_path,
            soundfile_module=playback.soundfile_module, volume=volume,
            level_callback=playback.level_callback, analysis_callback=playback.analysis_callback,
            level_fps=analysis_fps, logger=inputs.logger)

    def audio_bytes(chunk):
        source = getattr(chunk, "audio_source", None)
        if source is not None:
            return source.retained_bytes
        info = playback.soundfile_module.info(chunk.audio_path)
        return int(info.frames) * int(info.channels) * 4

    last_progress = [None]
    analysis_state = playback.analysis_state or audio_playback.VoiceAnalysisPlaybackState()
    analysis_audio = [None]
    first_voice_frame = [None]

    def observe(callback, value):
        if callable(callback):
            try:
                callback(value)
            except BaseException:
                pass

    def owns_effects():
        return selection[2] is stop_event

    def state_changed(state):
        if state == "speaking":
            if stop_event.is_set():
                return
            selection[2] = stop_event
            playback.audio_playing.set()
            analysis_state.begin(stop_event)
        else:
            if not owns_effects():
                return  # A retired epoch must not reset a replacement's live UI.
            playback.audio_playing.clear()
            last_progress[0] = None
            analysis_audio[0] = first_voice_frame[0] = None
            observe(playback.level_callback, 0.0)
            if owns_effects():
                observe(playback.analysis_callback, None)
        if owns_effects():
            observe(playback.state_callback, "speaking" if state == "speaking" else "idle")
        if state != "speaking" and owns_effects():
            selection[2] = None

    def progress(audio, media_seconds):
        if not owns_effects() or stop_event.is_set() or not audio.levels:
            return
        index = min(int(media_seconds * audio.level_fps), len(audio.levels) - 1)
        marker = (id(audio), index)
        if index < 0 or marker == last_progress[0]:
            return
        last_progress[0] = marker
        if analysis_audio[0] is not audio:
            analysis_audio[0], first_voice_frame[0] = audio, None
            if (callable(playback.analysis_callback) and audio.voice_frames
                    and audio.first_voice_block is not None and callable(audio_playback.analyze_voice_block)):
                try:
                    first_voice_frame[0] = audio_playback.analyze_voice_block(
                        audio.first_voice_block, audio.sample_rate, analysis_state.previous_spectrum)
                except BaseException:
                    pass  # Precomputed frames remain usable if optional analysis fails.
        observe(playback.level_callback, audio.levels[index])
        if not owns_effects() or stop_event.is_set():
            return
        if callable(playback.analysis_callback) and index < len(audio.voice_frames):
            frame = first_voice_frame[0] if index == 0 and first_voice_frame[0] is not None else audio.voice_frames[index]
            analysis_state.record(frame)
            observe(playback.analysis_callback, frame)

    clock_progress = {}

    def incremental_progress(chunk, audio, clock):
        source = getattr(chunk, "audio_source", None)
        if source is None or not owns_effects() or stop_event.is_set():
            return
        duration = audio.duration_seconds
        estimated = not source.finished
        marker = (int(clock.media_seconds * 30), clock.running, duration, estimated)
        previous = clock_progress.get(chunk.index)
        if previous is not None and previous[0] == marker:
            return
        fraction = min(.999999, max(0., clock.media_seconds / duration)) if duration > 0 else 0.
        fraction = max(previous[1] if previous is not None else 0., fraction)
        clock_progress[chunk.index] = (marker, fraction)
        events.local_audio_progress({
            "speech_id": chunk.speech_id, "sequence": chunk.index,
            "audio_media_seconds": clock.media_seconds,
            "audio_clock_monotonic": clock.sampled_monotonic,
            "audio_scheduled_through_seconds": clock.scheduled_through_seconds,
            "audio_clock_running": clock.running,
            "duration_seconds": duration, "audio_duration_estimated": estimated,
            "audio_progress_floor": fraction})

    effects = AudioFilePlaybackCapabilities(
        play_file=lambda path, **kwargs: _play_audio_file(inputs, path, **kwargs),
        delete_audio=runtime_files.safe_delete_with_retry,
        segment_started=events.segment_started,
        duck_start=lambda payload: duck_effects.start(stop_event, payload),
        duck_end=lambda payload: duck_effects.end(stop_event, payload),
        trace=events.trace, supports_audio_start=True)
    output = SoundDeviceSpeechSession(sounddevice_module=playback.sounddevice_module,
        stop_event=stop_event, output_device=output_device)
    if str(_runtime_config_values(inputs.tts.config).get("avatar_mode", "")).strip().lower() in ('none', 'ditto', 'musetalk', 'scenic'):
        from core.incremental_playback import IncrementalSpeechSession
        output = IncrementalSpeechSession(output)
    return LocalPlaybackSession(owner=owner, stop_event=stop_event,
        output=output,
        prepare_audio=prepare, effects=effects, audio_bytes_for=audio_bytes,
        state_callback=state_changed, progress_callback=progress,
        clock_progress_callback=incremental_progress)


def _visual_capabilities(inputs: ProductionDesktopVisualInputs) -> VisualCapabilities:
    addon = inputs.addon
    policy = VisualPolicyCapabilities(
        mode=addon.mode,
        enabled=addon.enabled,
        enabled_for=addon.enabled_for,
        generation_available=addon.generation_available,
        generation_available_for=addon.generation_available_for,
        story_mode_enabled=addon.story_mode_enabled,
        story_max_images=addon.story_max_images,
        story_continuity_strength=addon.story_continuity_strength,
        story_theme_prompts=addon.story_theme_prompts,
        story_theme_enabled=addon.story_theme_enabled,
        story_theme_suffix=addon.story_theme_suffix,
        master_style_prompt=addon.master_style_prompt,
        master_style_suffix=addon.master_style_suffix,
        master_prompt_safety_suffix=addon.master_prompt_safety_suffix,
        no_speech_bubbles_suffix=addon.no_speech_bubbles_suffix,
        apply_style_anchor=addon.apply_style_anchor,
        story_style_guide=addon.story_style_guide_from_text,
        story_prompt=addon.story_prompt_from_text,
        normalize_prompt=addon.normalize_prompt_text,
        strip_visual_tail=addon.strip_visual_reply_tail,
        looks_like_tag_prefix=addon.looks_like_visual_reply_tag_prefix,
        extract_prompt=addon.extract_visual_reply_prompt,
    )
    return VisualCapabilities(
        generate=addon.generate,
        publish_requested=addon.publish_requested,
        publish_result=addon.publish_result,
        publish_failure=addon.publish_failure,
        retire_request=getattr(addon, "retire_request", None),
        attach_history=inputs.attach_history,
        refresh_history=inputs.refresh_history,
        policy=policy,
    )


def _buddy_contextual_payload(request: Mapping[str, object]) -> dict[str, str]:
    source = str(request.get("source", "") or "").strip().lower()
    if not source or not any(token in source for token in ("spotify", "companion_orb")):
        return {}
    candidate = str(request.get("candidate", "") or "").strip()
    if not candidate:
        return {}
    context_parts = []
    for label, key in (("Summary", "summary"), ("Attention", "attention"), ("Focus", "focus_text")):
        value = str(request.get(key, "") or "").strip()
        if value:
            context_parts.append(f"{label}: {value}")
    return {
        "text": candidate,
        "source": source,
        "context": "\n".join(context_parts),
    }


def build_production_desktop_realtime_platform_inputs(
    inputs: ProductionDesktopRealtimeInputs,
) -> ProductionRealtimePlatformInputs:
    """Build the real desktop platform record from finite process leaves."""

    _validate_inputs(inputs)
    speech_module = inputs.speech.speech_module
    microphone = speech_module.Microphone
    event_adapter = _ProductionDesktopTtsEvents(inputs.addons, inputs.logger)

    output_selection = [None, None]
    events = ProductionTtsEvents(
        trace=event_adapter.trace,
        generation_started=event_adapter.generation_started,
        generation_finished=event_adapter.generation_finished,
        audio_chunk_ready=event_adapter.audio_chunk_ready,
        segment_started=event_adapter.segment_started,
        duck_start=event_adapter.duck_start,
        duck_end=event_adapter.duck_end,
        local_audio_progress=event_adapter.local_audio_progress,
    )
    return ProductionRealtimePlatformInputs(
        speech_input=ProductionSpeechInputPlatform(
            recognizer=inputs.speech.recognizer,
            microphone_factory=microphone,
            microphone_names=microphone.list_microphone_names,
            addon_resolver=inputs.speech_backends.resolve_stt_backend,
            speech_module=speech_module,
            audio_data_factory=speech_module.AudioData,
            microphone_active=inputs.speech.microphone_active,
            push_to_talk_held=inputs.speech.push_to_talk_held,
            set_push_to_talk_hold=inputs.speech.set_push_to_talk_hold,
            np_module=inputs.speech.np_module,
            tuning=inputs.speech.tuning,
            logger=inputs.logger,
            pcm_callback=inputs.speech.pcm_callback,
        ),
        tts=ProductionTtsPlatform(
            adapter_for=inputs.speech_backends.current_tts_adapter,
            sentence_splitter=inputs.tts.sentence_splitter,
            events=events,
            set_seed=inputs.tts.set_seed,
            logger=inputs.logger,
            prepare_playback_audio=lambda chunk, config: _prepare_playback_audio(inputs, chunk, config),
            incremental_pcm_allowed=lambda chunk, config: _incremental_pcm_allowed(inputs, chunk, config),
        ),
        playback=ProductionPlaybackPlatform(
            volume_for=lambda metadata, text: _playback_volume_for(
                inputs,
                metadata,
                text,
            ),
            events=events,
            play_file=lambda path, **kwargs: _play_audio_file(
                inputs,
                path,
                **kwargs,
            ),
            delete_audio=runtime_files.safe_delete_with_retry,
            supports_audio_start=True,
            open_local_session=lambda owner, stop: _open_local_session(inputs, events, owner, stop, output_selection),
        ),
        replay=ProductionReplayPlatform(
            events=events,
            resolve_voice=runtime_files.resolve_voice_reference_path,
        ),
        visual=ProductionVisualPlatform(
            capabilities=_visual_capabilities(inputs.visual),
            request_id_factory=inputs.visual.addon.next_request_id,
        ),
        sensory=ProductionSensoryPlatform(
            capabilities=SensoryCapabilities(
                orb_focus=inputs.sensory.orb_focus,
                avatar_emotion=inputs.sensory.avatar_emotion,
                proactive=inputs.sensory.proactive,
                visual=inputs.sensory.visual,
                publish_event=inputs.sensory.publish_event,
                request_chat_rebuild=inputs.sensory.request_chat_rebuild,
                log=inputs.logger,
                debug=inputs.sensory.debug,
                loop_ready=inputs.sensory.loop_ready,
                blocked_reasons=inputs.sensory.blocked_reasons,
                build_messages=inputs.sensory.build_messages,
                model_supports_images=inputs.sensory.model_supports_images,
                emotion_allowed=inputs.sensory.emotion_allowed,
                visual_allowed=inputs.sensory.visual_allowed,
                proactive_ready=inputs.sensory.proactive_ready,
                buddy_contextual_payload=_buddy_contextual_payload,
                output_directory=(
                    Path(inputs.app_root).resolve() / "runtime" / "sensory_feedback"
                ),
                auto_start_hidden_loop=True,
            ),
            registry=sensory.get_registry(),
        ),
        interaction=ProductionInteractionPlatform(
            check_barge_in=inputs.interaction.check_barge_in,
            dry_run_active=inputs.interaction.dry_run_active,
            push_to_talk_gui_held=inputs.interaction.push_to_talk_gui_held,
            queue_size=inputs.interaction.queue_size,
            is_hotkey_pressed=runtime_hotkeys.is_hotkey_binding_pressed,
            bind_hotkeys=runtime_hotkeys.bind_hotkey_state_tracker,
            unbind_hotkeys=runtime_hotkeys.unbind_hotkey_state_tracker,
            logger=inputs.logger,
        ),
    )


def build_production_desktop_realtime_owners(
    inputs: ProductionDesktopRealtimeInputs,
) -> ProductionRealtimeOwners:
    """Build the finite production owners for the concrete desktop process."""

    return build_production_realtime_platform(
        build_production_desktop_realtime_platform_inputs(inputs)
    )


__all__ = [
    "DesktopAddonCapabilityPort",
    "DesktopRuntimeConfigSource",
    "DesktopSpeechBackendOwner",
    "DesktopVisualReplyCapabilities",
    "ProductionDesktopInteractionInputs",
    "ProductionDesktopPlaybackInputs",
    "ProductionDesktopRealtimeInputs",
    "ProductionDesktopSensoryInputs",
    "ProductionDesktopSpeechInputs",
    "ProductionDesktopTtsInputs",
    "ProductionDesktopVisualInputs",
    "build_production_desktop_realtime_owners",
    "build_production_desktop_realtime_platform_inputs",
]
