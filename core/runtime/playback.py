"""Serialized owner for prepared speech playback and terminal accounting."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import queue
import threading
import time
import tempfile
import wave
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.local_playback import LocalPlaybackSession
    from core.continuous_audio import AudioClockSample

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.controllers import (
    ControllerCancellationSignal,
    ControllerRegistrationHandle,
    ControllerSetupFailure,
    ControllerSetupLease,
    ControllerSetupRegistry,
    ControllerSetupTransaction,
    RouteEffectOwner,
)
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerSupervisor
from core.musetalk_startup import first_chunk_plan_sync_wait_seconds


class PlaybackDevice(Protocol):
    def play(self, chunk: object, stop_event: object, owner: "PlaybackOwner") -> object: ...

    def stop(self, owner: "PlaybackOwner") -> object: ...


class PreparedStream(Protocol):
    @property
    def done(self) -> bool: ...

    @property
    def cancelled(self) -> bool: ...

    @property
    def failure(self) -> RuntimeFailure | None: ...

    def next_ready(self, timeout=None, *, admit_lease=None) -> object | None: ...

    def cancel(self, reason: str = "speech_cancelled") -> None: ...


LeasePredicate = Callable[[WorkLease], bool]
EventFactory = Callable[[], object]


def _noop_effect(_payload: Mapping[str, object]) -> object:
    return None


def _default_volume(_metadata: Mapping[str, object], _text: str) -> float:
    return 1.0


def _wav_duration_seconds(path: str) -> float:
    """Read one WAV header without decoding audio; return zero on bad input."""

    candidate = str(path or "").strip()
    if not candidate:
        return 0.0
    try:
        with wave.open(candidate, "rb") as audio:
            sample_rate = int(audio.getframerate() or 0)
            if sample_rate <= 0:
                return 0.0
            return max(0.0, float(audio.getnframes()) / float(sample_rate))
    except (OSError, EOFError, wave.Error):
        return 0.0


@dataclass(frozen=True, slots=True)
class AudioFilePlaybackCapabilities:
    """Explicit production effects for prepared audio-file playback."""

    play_file: Callable[..., object]
    delete_audio: Callable[[str], object]
    volume_for: Callable[[Mapping[str, object], str], float] = _default_volume
    segment_started: Callable[[Mapping[str, object]], object] = _noop_effect
    duck_start: Callable[[Mapping[str, object]], object] = _noop_effect
    duck_end: Callable[[Mapping[str, object]], object] = _noop_effect
    trace: Callable[[str, Mapping[str, object]], object] = lambda _event, _fields: None
    supports_audio_start: bool = False
    open_local_session: Callable[[PlaybackOwner, object], LocalPlaybackSession | None] | None = None


class AudioFilePlaybackDevice:
    """Play prepared audio on PlaybackService's single serialized worker."""

    def __init__(self, capabilities: AudioFilePlaybackCapabilities) -> None:
        self._capabilities = capabilities
        self._fallback_lock = threading.Lock()
        self._fallback_source = None

    @property
    def supports_audio_start(self) -> bool:
        return self._capabilities.supports_audio_start

    def open_local_session(self, owner, stop_event):
        factory = self._capabilities.open_local_session
        return factory(owner, stop_event) if factory is not None else None

    def play(self, chunk: object, stop_event: object, owner: "PlaybackOwner", *, on_started=None) -> None:
        source = getattr(chunk, "audio_source", None)
        if source is None:
            return self._play_file(chunk, stop_event, owner, on_started=on_started)
        if getattr(source, 'avatar_gate', None) is not None:
            # Serial file playback cannot enforce per-frame avatar admission.
            # Fail closed rather than let the audio outrun its prepared visuals.
            source.cancel('progressive_avatar_output_unavailable')
            source.close()
            raise RuntimeError('Progressive avatar audio requires a working local streaming output.')
        # No PCM has reached a device on this route. Complete the existing
        # request into a real owned WAV instead of resynthesizing its prefix.
        path = ""
        with self._fallback_lock:
            self._fallback_source = (owner, source)
        try:
            if stop_event.is_set():
                source.cancel("playback_stopped")
            source.wait_finished()
            if stop_event.is_set():
                raise InterruptedError("Playback stopped before completed-audio fallback")
            with tempfile.NamedTemporaryFile(prefix="nc-pcm-fallback-", suffix=".wav",
                    dir=source.output_directory, delete=False) as output:
                path = output.name
            source.write_wav(path)
            complete = replace(chunk, audio_path=path, playback_audio=None, audio_source=None)
            return self._play_file(complete, stop_event, owner,
                on_started=on_started, delete_audio=False)
        finally:
            with self._fallback_lock:
                if self._fallback_source == (owner, source):
                    self._fallback_source = None
            source.close()
            if path:
                try:
                    self._capabilities.delete_audio(path)
                except BaseException:
                    pass

    def _play_file(self, chunk, stop_event, owner, *, on_started=None, delete_audio=True):
        metadata = dict(getattr(chunk, "source_metadata", {}) or {})
        text = str(getattr(chunk, "text", "") or "")
        expression = str(getattr(chunk, "expression", "") or "")
        path = str(getattr(chunk, "audio_path", "") or "")
        sequence = int(getattr(chunk, "index", 0) or 0)
        duration_seconds = _wav_duration_seconds(path)
        payload = {
            "source": "tts_playback",
            "text": text,
            "emotion": expression,
            "sequence_index": sequence,
            "persona_id": str(metadata.get("persona_id", "") or ""),
            "display_name": str(metadata.get("display_name", "") or ""),
            "replay": bool(metadata.get("tts_replay", False)),
            "replay_index": int(metadata.get("replay_index", 0) or 0),
        }
        ducked = False
        started_at = time.perf_counter()
        try:
            self._effect(self._capabilities.segment_started, payload)
            ducked = bool(self._effect(self._capabilities.duck_start, payload))
            self._trace(
                "tts_chunk_playback_start",
                {
                    "trace_id": str(metadata.get("tts_trace_id", "") or ""),
                    "text": text,
                    "sequence": sequence,
                    "replay": bool(metadata.get("tts_replay", False)),
                    "replay_index": int(metadata.get("replay_index", 0) or 0),
                    "owner_generation": owner.generation,
                    "duration_seconds": duration_seconds,
                },
            )
            if path and not bool(metadata.get("skip_local_playback", False)):
                volume = float(self._capabilities.volume_for(metadata, text) or 0.0)
                timing_options = {}
                if self.supports_audio_start:
                    timing_options = {
                        "prepared_audio": getattr(chunk, "playback_audio", None),
                        "on_started": on_started,
                    }
                self._capabilities.play_file(
                    path,
                    stop_event=stop_event,
                    volume=volume,
                    **timing_options,
                )
        finally:
            self._trace(
                "tts_chunk_playback_end",
                {
                    "trace_id": str(metadata.get("tts_trace_id", "") or ""),
                    "duration_ms": round(
                        max(0.0, (time.perf_counter() - started_at) * 1000.0),
                        3,
                    ),
                    "sequence": sequence,
                    "replay": bool(metadata.get("tts_replay", False)),
                    "replay_index": int(metadata.get("replay_index", 0) or 0),
                },
            )
            if ducked:
                self._effect(
                    self._capabilities.duck_end,
                    {"source": "tts_playback", "reason": "completed"},
                )
            if path and delete_audio:
                try:
                    self._capabilities.delete_audio(path)
                except BaseException:
                    pass

    def stop(self, owner: "PlaybackOwner") -> None:
        with self._fallback_lock:
            active = self._fallback_source
        if active is not None and active[0] is owner:
            active[1].cancel("playback_stopped")

    @staticmethod
    def _effect(callback, payload):
        try:
            return callback(dict(payload))
        except BaseException:
            return None

    def _trace(self, event: str, fields: Mapping[str, object]) -> None:
        try:
            self._capabilities.trace(str(event), dict(fields))
        except BaseException:
            pass


@dataclass(frozen=True, slots=True)
class PlaybackOwner:
    generation: int
    lease: WorkLease


@dataclass(frozen=True, slots=True)
class DeliveredChunk:
    index: int
    text: str
    lease: WorkLease
    owner_generation: int
    audio_start_pending: bool = False
    audio_started_monotonic: float | None = None
    audio_clock_sample: AudioClockSample | None = None


@dataclass(frozen=True, slots=True)
class PlaybackRoute:
    stream: object
    lease: WorkLease
    owner: PlaybackOwner
    effect_owner: RouteEffectOwner | None = None
    observer: PlaybackObserver | None = None


@dataclass(frozen=True, slots=True)
class PlaybackSnapshot:
    current: PlaybackRoute | None
    next: PlaybackRoute | None
    paused: bool
    terminal: bool
    stopping: bool


@dataclass(frozen=True, slots=True)
class PlaybackReceipt:
    delivered_chunks: tuple[DeliveredChunk, ...]
    terminal_reason: str
    owner: PlaybackOwner | None = None
    failure: RuntimeFailure | None = None

    @property
    def delivered_chunk_indexes(self) -> tuple[int, ...]:
        return tuple(chunk.index for chunk in self.delivered_chunks)


class PlaybackObserver(Protocol):
    """Low-frequency admission notifications for non-device runtime services."""

    def on_playback_started(self, chunk: DeliveredChunk) -> None: ...

    def on_playback_paused(self, owner: PlaybackOwner) -> None: ...

    def on_playback_finished(self, receipt: PlaybackReceipt) -> None: ...


@dataclass(frozen=True, slots=True)
class QueuedPlaybackChunk:
    index: int
    text: str
    lease: WorkLease
    payload: object
    source_metadata: Mapping[str, object] | None = None


class PreparationEffectAdmission:
    def __init__(self, gate: "PreparationEffectGate") -> None:
        self._gate = gate
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._gate._release()


class PreparationEffectGate:
    """Seal producer effects and wait boundedly for already-admitted effects."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._closed = False
        self._active = 0

    def begin(self) -> PreparationEffectAdmission | None:
        with self._condition:
            if self._closed:
                return None
            self._active += 1
        return PreparationEffectAdmission(self)

    def close(self, timeout: float = 0.5) -> RuntimeFailure | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            self._closed = True
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return RuntimeFailure(
                        "playback_effect_stop_timeout",
                        "A preparation effect did not finish before playback cancellation",
                    )
                self._condition.wait(remaining)
        return None

    def _release(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()


class QueuePlaybackStream:
    """Ordered queue adapter used by the temporary legacy speech entry point."""

    playback_callback_consumes_stream = True

    def __init__(
        self,
        source,
        lease: WorkLease,
        playback_callback: Callable[..., object],
        *,
        seal_effects: Callable[[], object] | None = None,
        cancel_preparation: Callable[[], object] | None = None,
        close_preparation: Callable[[], object] | None = None,
        producer_threads: tuple[threading.Thread, ...] = (),
        cleanup_sources: tuple[object, ...] = (),
        cleanup_item: Callable[[object], object] | None = None,
        speech_id: str = "",
        close_callback: Callable[[], object] | None = None,
        skip_current_message: Callable[[], bool] | None = None,
        join_timeout_seconds: float = 0.5,
    ) -> None:
        self.lease = lease
        self.speech_id = str(speech_id or "")
        self.playback_callback = playback_callback
        self._source = source
        self._done = False
        self._cancelled = False
        self._failure: RuntimeFailure | None = None
        self._seal_effects = seal_effects
        self._cancel_preparation = cancel_preparation
        self._close_preparation = close_preparation
        self._producer_threads = tuple(producer_threads)
        self._cleanup_sources = (source, *tuple(cleanup_sources))
        self._cleanup_item = cleanup_item
        self._close_callback = close_callback
        self._skip_current_message = skip_current_message
        self._join_timeout_seconds = max(0.0, float(join_timeout_seconds))
        self._cancel_lock = threading.Lock()
        self._cancel_condition = threading.Condition(self._cancel_lock)
        self._cancel_in_progress = False
        self._cleanup_complete = False
        self._close_lock = threading.Lock()
        self._closed = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def failure(self) -> RuntimeFailure | None:
        return self._failure

    def next_ready(self, timeout=None, *, admit_lease=None):
        admission = admit_lease(self.lease) if admit_lease is not None else self
        if admission is None:
            return None
        try:
            item = self._source.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            self._done = True
            return None
        admission = admit_lease(self.lease) if admit_lease is not None else self
        if admission is None:
            self._cleanup_item_outside_lock(item)
            return None
        index = int(item[3] if len(item) > 3 else 0)
        text = str(item[2] if len(item) > 2 else "")
        metadata = (
            dict(item[5] or {})
            if len(item) > 5 and isinstance(item[5], Mapping)
            else {}
        )
        return QueuedPlaybackChunk(index, text, self.lease, item, metadata)

    def cancel(self, reason: str = "speech_cancelled") -> None:
        del reason
        deadline = time.monotonic() + self._join_timeout_seconds
        with self._cancel_condition:
            if self._cleanup_complete:
                return
            if self._cancel_in_progress:
                while not self._cleanup_complete:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        if self._failure is None:
                            self._failure = RuntimeFailure(
                                "playback_cancel_wait_timeout",
                                "Concurrent playback cancellation did not finish in time",
                            )
                        return
                    self._cancel_condition.wait(remaining)
                return
            self._cancel_in_progress = True
            self._cancelled = True
            seal_effects = self._seal_effects
            self._seal_effects = None
            callback = self._cancel_preparation
            self._cancel_preparation = None
            self._close_preparation = None
            cleanup_sources = self._cleanup_sources
            self._cleanup_sources = ()
            producer_threads = self._producer_threads

        if callable(seal_effects):
            try:
                effect_failure = seal_effects()
                if isinstance(effect_failure, RuntimeFailure):
                    self._failure = effect_failure
            except BaseException:
                pass
        if callable(callback):
            try:
                callback()
            except BaseException:
                pass
        try:
            for worker in producer_threads:
                if worker is threading.current_thread():
                    continue
                remaining = max(0.0, deadline - time.monotonic())
                worker.join(remaining)
            for source in cleanup_sources:
                self._drain_source(source)
            surviving = tuple(worker.name for worker in producer_threads if worker.is_alive())
            if surviving and self._failure is None:
                self._failure = RuntimeFailure(
                    "playback_producer_stop_timeout",
                    f"Playback producers did not stop: {', '.join(surviving)}",
                )
        finally:
            with self._cancel_condition:
                self._cancel_in_progress = False
                self._cleanup_complete = True
                self._cancel_condition.notify_all()
            self.close()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            callback = self._close_callback
            self._close_callback = None
        with self._cancel_condition:
            close_preparation = self._close_preparation
            self._close_preparation = None
        if callable(close_preparation):
            try:
                close_preparation()
            except BaseException:
                pass
        if callable(callback):
            try:
                callback()
            except BaseException:
                pass

    def request_skip_current_message(self) -> bool:
        callback = self._skip_current_message
        if not callable(callback):
            return False
        try:
            return bool(callback())
        except BaseException:
            return False

    def mark_done(self) -> None:
        self._done = True

    def discard_ready(self, chunk: object) -> None:
        item = getattr(chunk, "payload", chunk)
        self._cleanup_item_outside_lock(item)

    def ready_chunks(self) -> tuple[QueuedPlaybackChunk, ...]:
        try:
            with self._source.mutex:
                items = tuple(self._source.queue)
        except BaseException:
            return ()
        ready = []
        for item in items:
            if not isinstance(item, tuple):
                continue
            index = int(item[3] if len(item) > 3 else 0)
            text = str(item[2] if len(item) > 2 else "")
            metadata = (
                dict(item[5] or {})
                if len(item) > 5 and isinstance(item[5], Mapping)
                else {}
            )
            ready.append(QueuedPlaybackChunk(index, text, self.lease, item, metadata))
        return tuple(ready)

    def has_live_producers(self) -> bool:
        return any(worker.is_alive() for worker in self._producer_threads)

    def bind_producer_threads(
        self,
        producer_threads: tuple[threading.Thread, ...],
    ) -> bool:
        with self._cancel_condition:
            if self._cancel_in_progress or self._cleanup_complete:
                return False
            self._producer_threads = tuple(producer_threads)
            return True

    def _drain_source(self, source: object) -> None:
        while True:
            try:
                item = source.get_nowait()
            except queue.Empty:
                return
            except BaseException:
                return
            if item is None or not callable(self._cleanup_item):
                continue
            try:
                self._cleanup_item(item)
            except BaseException:
                pass

    def _cleanup_item_outside_lock(self, item: object) -> None:
        if item is None or not callable(self._cleanup_item):
            return
        try:
            self._cleanup_item(item)
        except BaseException:
            pass


class _RouteWorkerCancellation:
    __slots__ = ("_route", "_worker")

    def __init__(self, worker, route) -> None:
        self._worker = worker
        self._route = route

    @property
    def cancelled(self) -> bool:
        return bool(self._worker.cancelled or self._route.cancelled)

    @property
    def reason(self) -> str:
        return str(self._worker.reason or self._route.reason or "")

    def is_set(self) -> bool:
        return self.cancelled

    def wait(self, timeout: float | None = None) -> bool:
        return self._route.wait(timeout)

    def set(self) -> None:
        self._worker.cancel("route_worker_cancelled")
        self._route.cancel("route_worker_cancelled")


def spawn_route_worker(
    workers: WorkerSupervisor,
    owner: RouteEffectOwner,
    *,
    name: str,
    lease: WorkLease,
    target: Callable[[object, RouteEffectOwner], object],
):
    child_result = owner.fork(name)
    if not child_result.accepted or child_result.value is None:
        return CommandResult(False, failure=child_result.failure)
    child = child_result.value

    def run(token) -> None:
        try:
            if token.cancelled or child.cancellation.cancelled:
                return
            cancellation = _RouteWorkerCancellation(token, child.cancellation)
            child.run_step(name, lambda: target(cancellation, child))
        finally:
            child.close()

    spawned = owner.run_step(
        f"{name}_spawn",
        lambda: workers.spawn(
            name=name,
            lease=lease,
            target=run,
            on_cancel=lambda reason: child.cancellation.cancel(reason),
            identity=child,
        ),
    )
    if not spawned.accepted:
        child.close()
    return spawned


@dataclass(frozen=True, slots=True)
class ReplayPlaybackRuntime:
    replay_id: str
    lease: WorkLease
    config: Mapping[str, object]
    source_text: str
    started_at: float
    controller_registry: ControllerSetupRegistry
    setup: ControllerSetupLease


@dataclass(frozen=True, slots=True)
class ReplayPlaybackPipelineSession:
    preprocess: Callable[[], object]
    playback_callback: Callable[..., object]
    registration: ControllerRegistrationHandle
    cancel: Callable[[], object] = lambda: None
    close: Callable[[], object] = lambda: None
    skip_current_message: Callable[[], bool] = lambda: False


@dataclass(frozen=True, slots=True)
class ReplayPlaybackPreparation:
    stream: QueuePlaybackStream
    registration: ControllerRegistrationHandle
    start: Callable[[RouteEffectOwner], CommandResult[None]]


@dataclass(frozen=True, slots=True)
class LegacyReplayPlaybackSessionCapabilities:
    """Explicit engine effects needed to open one Task 14 replay session."""

    controller_factory: Callable[[], object]
    bind_playback_skip: Callable[[object], object]
    reset_playback_state: Callable[[], object]
    avatar_gui: Callable[[], object | None]
    begin_pipeline_reply: Callable[[], object]
    update_pipeline_flags: Callable[[object, str], object]
    reset_pipeline_data: Callable[[], object]
    story_mode_enabled: Callable[[], bool]
    story_max_images: Callable[[], int]
    story_generation_available: Callable[[], bool]
    begin_story_session: Callable[[], int]
    story_style_guide: Callable[[str], str]
    effect_gate_factory: Callable[[], object]
    preprocess: Callable[[dict[str, object]], object]
    playback_effects: Callable[
        [
            object,
            str,
            Mapping[str, object],
            bool,
            object,
            object,
            object,
            ReplayPlaybackRuntime,
            dict[str, object],
        ],
        Callable[..., object],
    ]


@dataclass(frozen=True, slots=True)
class LegacyNormalSpeechSetupCapabilities:
    reset_playback_state: Callable[[], object]
    avatar_gui: Callable[[], object | None]
    tts_available: Callable[[], bool]
    report_tts_unavailable: Callable[[], object]
    set_presence_state_idle: Callable[[], object]
    clear_presence_audio_level: Callable[[], object]
    resolve_voice: Callable[[str], str]
    report_voice_unavailable: Callable[[str], object]
    record_pipeline_start: Callable[[Mapping[str, object]], object]
    begin_pipeline_reply: Callable[[bool], object]
    update_pipeline_flags: Callable[[object, str], object]
    reset_pipeline_data: Callable[[], object]
    story_mode_enabled: Callable[[], bool]
    story_max_images: Callable[[], int]
    story_generation_available: Callable[[], bool]
    report_story_unavailable: Callable[[], object]
    begin_story_session: Callable[[], int]
    story_continuity_strength: Callable[[], object]
    story_style_guide: Callable[[str, object], str]
    effect_gate_factory: Callable[[], object]


@dataclass(frozen=True, slots=True)
class LegacyNormalSpeechRouteCapabilities:
    """Explicit effects used to publish one exact normal-speech route."""

    playback_service: "PlaybackService"
    workers: WorkerSupervisor
    run_generator: Callable[[object, RouteEffectOwner], object]
    run_preprocessor: Callable[[object, RouteEffectOwner], object]
    cleanup_item: Callable[[object], object]
    cancel_preparation: Callable[[], object]
    cancel_route: Callable[[], object]
    bind_playback_cancel: Callable[[QueuePlaybackStream], object]
    close_stream: Callable[[], object]
    retire_controller: Callable[[], object]


def prepare_legacy_normal_speech_setup(
    transaction: ControllerSetupTransaction,
    state: Mapping[str, object],
    capabilities: LegacyNormalSpeechSetupCapabilities,
) -> dict[str, object] | None:
    """Run normal speech setup effects under one exact active transaction."""

    def run_step(operation):
        result = transaction.run_step(operation)
        if not result.accepted:
            raise ControllerSetupFailure(
                result.failure
                or RuntimeFailure(
                    "controller_setup_stale",
                    "The exact normal speech setup is no longer active.",
                )
            )
        return result.value

    run_step(capabilities.reset_playback_state)
    avatar_gui = run_step(capabilities.avatar_gui)
    if avatar_gui is not None:

        def begin_avatar_reply() -> None:
            try:
                avatar_gui.begin_reply()
            except BaseException:
                pass

        run_step(begin_avatar_reply)
    if not bool(run_step(capabilities.tts_available)):
        run_step(capabilities.report_tts_unavailable)
        run_step(capabilities.set_presence_state_idle)
        run_step(capabilities.clear_presence_audio_level)
        return None

    prepared = dict(state)
    voice_path_override = str(prepared.get("voice_path_override", "") or "")
    resolved_voice_path_override = ""
    if voice_path_override:
        resolved_voice_path_override = str(
            run_step(lambda: capabilities.resolve_voice(voice_path_override)) or ""
        )
        if not resolved_voice_path_override:
            run_step(lambda: capabilities.report_voice_unavailable(voice_path_override))

    replay_mode = bool(prepared.get("replay_items"))
    playback_queue = queue.Queue(maxsize=6 if replay_mode else 0)
    ready_for_playback = queue.Queue(maxsize=6 if replay_mode else 0)
    turn_config = prepared.get("turn_config", {})
    if not isinstance(turn_config, Mapping):
        turn_config = {}
    avatar_mode = str(turn_config.get("avatar_mode", "vseeface") or "vseeface").lower()
    streamed = bool(
        prepared.get("text_iterable") is not None
        or turn_config.get("stream_mode", False)
    )
    run_step(
        lambda: capabilities.record_pipeline_start(
            {
                "avatar_mode": avatar_mode,
                "input_chars": len(str(prepared.get("text", "") or "")),
                "latency_trace_id": prepared.get("latency_trace_id", ""),
                "replay_mode": replay_mode,
                "streamed": streamed,
                "turn_config": turn_config,
            }
        )
    )
    pipeline_telemetry_enabled = avatar_mode in {"musetalk", "none"}
    pipeline_reply_id = None
    if pipeline_telemetry_enabled:
        pipeline_reply_id = run_step(
            lambda: capabilities.begin_pipeline_reply(streamed)
        )
        run_step(
            lambda: capabilities.update_pipeline_flags(
                pipeline_reply_id,
                avatar_mode,
            )
        )
    else:
        run_step(capabilities.reset_pipeline_data)

    story_mode_enabled = bool(run_step(capabilities.story_mode_enabled))
    story_max_images = int(run_step(capabilities.story_max_images))
    story_generation_available = bool(
        story_mode_enabled and run_step(capabilities.story_generation_available)
    )
    story_session_id = 0
    story_style_guide = ""
    effect_gate = run_step(capabilities.effect_gate_factory)
    if story_mode_enabled and not story_generation_available:
        run_step(capabilities.report_story_unavailable)
    elif story_mode_enabled:
        story_session_id = int(run_step(capabilities.begin_story_session))
        continuity_strength = run_step(capabilities.story_continuity_strength)
        story_style_guide = str(
            run_step(
                lambda: capabilities.story_style_guide(
                    str(prepared.get("text", "") or ""),
                    continuity_strength,
                )
            )
            or ""
        )

    prepared.update(
        {
            "avatar_mode": avatar_mode,
            "effect_gate": effect_gate,
            "pipeline_reply_id": pipeline_reply_id,
            "pipeline_telemetry_enabled": pipeline_telemetry_enabled,
            "playback_queue": playback_queue,
            "ready_for_playback": ready_for_playback,
            "replay_mode": replay_mode,
            "resolved_voice_path_override": resolved_voice_path_override,
            "story_generation_available": story_generation_available,
            "story_images_requested": 0,
            "story_max_images": story_max_images,
            "story_session_id": story_session_id,
            "story_style_guide": story_style_guide,
        }
    )
    prepared.pop("voice_path_override", None)
    return prepared


def publish_legacy_normal_speech_route(
    transaction: ControllerSetupTransaction,
    lease: WorkLease,
    preparation_state: Mapping[str, object],
    playback_effects: Callable[..., object],
    preparation_effect_gate: object,
    capabilities: LegacyNormalSpeechRouteCapabilities,
) -> tuple[QueuePlaybackStream, "PlaybackOwner", RouteEffectOwner]:
    """Transfer setup and publish producers under exact route authority."""

    playback_owner = None
    route_owner = None
    try:
        reserved = capabilities.playback_service.reserve_owner(lease)
        if not reserved.accepted or reserved.value is None:
            raise ControllerSetupFailure(
                reserved.failure
                or RuntimeFailure(
                    "playback_owner_stale",
                    "The exact playback owner could not be reserved.",
                )
            )
        playback_owner = reserved.value
        published = transaction.publish()
        if not published.accepted:
            raise ControllerSetupFailure(
                published.failure
                or RuntimeFailure(
                    "controller_setup_stale",
                    "The exact normal speech setup could not be published.",
                )
            )
        activated = transaction.registry.activate_route(
            transaction.registration,
            playback_owner,
        )
        if not activated.accepted or activated.value is None:
            raise ControllerSetupFailure(
                activated.failure
                or RuntimeFailure(
                    "route_effect_stale",
                    "The exact normal speech route could not own effects.",
                )
            )
        route_owner = activated.value
        generator = spawn_route_worker(
            capabilities.workers,
            route_owner,
            name="nc-tts-generator",
            lease=lease,
            target=capabilities.run_generator,
        )
        preprocessor = spawn_route_worker(
            capabilities.workers,
            route_owner,
            name="nc-tts-preprocessor",
            lease=lease,
            target=capabilities.run_preprocessor,
        )
        if (
            not generator.accepted
            or generator.value is None
            or not preprocessor.accepted
            or preprocessor.value is None
        ):
            raise ControllerSetupFailure(
                generator.failure
                or preprocessor.failure
                or RuntimeFailure(
                    "route_effect_stale",
                    "Normal speech producers lost route authority before spawn.",
                )
            )
        playback_queue = preparation_state["playback_queue"]
        ready_for_playback = preparation_state["ready_for_playback"]
        stream_result = route_owner.run_step(
            "playback_stream_publish",
            lambda: QueuePlaybackStream(
                ready_for_playback,
                lease,
                playback_effects,
                seal_effects=preparation_effect_gate.close,
                cancel_preparation=capabilities.cancel_preparation,
                producer_threads=(
                    generator.value.thread,
                    preprocessor.value.thread,
                ),
                cleanup_sources=(playback_queue,),
                cleanup_item=capabilities.cleanup_item,
                close_callback=capabilities.close_stream,
            ),
        )
        if not stream_result.accepted or stream_result.value is None:
            raise ControllerSetupFailure(
                stream_result.failure
                or RuntimeFailure(
                    "route_effect_stale",
                    "Normal speech stream lost route authority before publication.",
                )
            )
        stream = stream_result.value
        bound = route_owner.run_step(
            "playback_cancel_binding",
            lambda: capabilities.bind_playback_cancel(stream),
        )
        if not bound.accepted:
            raise ControllerSetupFailure(
                bound.failure
                or RuntimeFailure(
                    "route_effect_stale",
                    "Normal speech cancellation lost route authority.",
                )
            )
        return stream, playback_owner, route_owner
    except BaseException:
        if route_owner is not None:
            route_owner.close()
            capabilities.cancel_route()
            capabilities.retire_controller()
        if playback_owner is not None:
            capabilities.playback_service.release_owner(playback_owner)
        raise


class LegacyReplayPlaybackSessionFactory:
    """Open the production preprocessor/effects pair for one exact replay."""

    def __init__(self, capabilities: LegacyReplayPlaybackSessionCapabilities) -> None:
        self._capabilities = capabilities

    def open_session(
        self,
        runtime: ReplayPlaybackRuntime,
        playback_queue: object,
        ready_for_playback: object,
    ) -> ReplayPlaybackPipelineSession:
        capabilities = self._capabilities
        controller = capabilities.controller_factory()
        activation = runtime.controller_registry.activate(
            runtime.setup,
            controller,
            ControllerCancellationSignal.from_events(
                getattr(controller, "cancel_requested", None),
                getattr(controller, "preparation_cancel_requested", None),
                getattr(controller, "skip_current_message", None),
            ),
        )
        if not activation.accepted or activation.value is None:
            try:
                controller.cancel_preparation()
            except BaseException:
                pass
            try:
                controller.done.set()
            except BaseException:
                pass
            raise ControllerSetupFailure(
                activation.failure
                or RuntimeFailure(
                    "controller_setup_stale",
                    "The exact replay setup could not activate its controller.",
                )
            )
        registration = activation.value
        retirement_lock = threading.Lock()
        retired = False

        def retire() -> None:
            nonlocal retired
            with retirement_lock:
                if retired:
                    return
                retired = True
            try:
                runtime.controller_registry.retire(registration)
            except BaseException:
                pass
            try:
                controller.done.set()
            except BaseException:
                pass

        def run_setup_step(operation):
            result = runtime.controller_registry.run_step(runtime.setup, operation)
            if not result.accepted:
                raise ControllerSetupFailure(
                    result.failure
                    or RuntimeFailure(
                        "controller_setup_stale",
                        "The exact replay setup is no longer active.",
                    )
                )
            return result.value

        try:
            run_setup_step(lambda: capabilities.bind_playback_skip(controller))
            run_setup_step(capabilities.reset_playback_state)
            avatar_gui = run_setup_step(capabilities.avatar_gui)
            if avatar_gui is not None:
                def begin_avatar_reply() -> None:
                    try:
                        avatar_gui.begin_reply()
                    except BaseException:
                        pass

                run_setup_step(begin_avatar_reply)

            avatar_mode = str(
                runtime.config.get("avatar_mode", "vseeface") or "vseeface"
            ).lower()
            pipeline_telemetry_enabled = avatar_mode in {"musetalk", "none"}
            pipeline_reply_id = None
            if pipeline_telemetry_enabled:
                pipeline_reply_id = run_setup_step(capabilities.begin_pipeline_reply)
                run_setup_step(
                    lambda: capabilities.update_pipeline_flags(
                        pipeline_reply_id,
                        avatar_mode,
                    )
                )
            else:
                run_setup_step(capabilities.reset_pipeline_data)

            story_mode_enabled = bool(run_setup_step(capabilities.story_mode_enabled))
            story_max_images = int(run_setup_step(capabilities.story_max_images))
            story_generation_available = bool(
                story_mode_enabled
                and run_setup_step(capabilities.story_generation_available)
            )
            story_session_id = 0
            story_style_guide = ""
            if story_mode_enabled and not story_generation_available:
                run_setup_step(
                    lambda: print(
                        "[VisualReply] Story mode is enabled, but visual reply "
                        "generation is unavailable."
                    )
                )
            elif story_mode_enabled:
                story_session_id = int(run_setup_step(capabilities.begin_story_session))
                story_style_guide = str(
                    run_setup_step(
                        lambda: capabilities.story_style_guide(runtime.source_text)
                    )
                    or ""
                )

            effect_gate = run_setup_step(capabilities.effect_gate_factory)
            preparation_state: dict[str, object] = {
                "avatar_mode": avatar_mode,
                "ctrl": controller,
                "dry_run_reply_id": None,
                "effect_gate": effect_gate,
                "latency_trace_id": runtime.replay_id,
                "pipeline_reply_id": pipeline_reply_id,
                "pipeline_telemetry_enabled": pipeline_telemetry_enabled,
                "playback_queue": playback_queue,
                "preserve_text_iterable_chunks": False,
                "ready_for_playback": ready_for_playback,
                "replay_items": (),
                "replay_mode": True,
                "reply_source_meta": None,
                "resolved_voice_path_override": "",
                "speak_started_at": runtime.started_at,
                "story_generation_available": story_generation_available,
                "story_images_requested": 0,
                "story_max_images": story_max_images,
                "story_session_id": story_session_id,
                "story_style_guide": story_style_guide,
                "text": runtime.source_text,
                "text_iterable": None,
                "turn_config": runtime.config,
                "turn_lease": runtime.lease,
            }
            playback_effects = run_setup_step(
                lambda: capabilities.playback_effects(
                    controller,
                    avatar_mode,
                    runtime.config,
                    pipeline_telemetry_enabled,
                    pipeline_reply_id,
                    playback_queue,
                    ready_for_playback,
                    runtime,
                    preparation_state,
                )
            )
        except BaseException:
            try:
                controller.cancel_preparation()
            except BaseException:
                pass
            retire()
            raise

        return ReplayPlaybackPipelineSession(
            preprocess=lambda: capabilities.preprocess(preparation_state),
            playback_callback=playback_effects,
            registration=registration,
            cancel=controller.cancel_preparation,
            close=retire,
            skip_current_message=controller.request_skip_current_message,
        )


@dataclass(frozen=True, slots=True)
class ReplayPlaybackPipelineCapabilities:
    open_session: Callable[
        [ReplayPlaybackRuntime, object, object],
        ReplayPlaybackPipelineSession,
    ]
    delete_audio: Callable[[str], object]
    trace: Callable[[str, Mapping[str, object]], object] = (
        lambda _event, _fields: None
    )
    emits_preprocess_trace: bool = False


class _ReplaySourceQueue(queue.Queue):
    def __init__(self, maxsize: int, started: dict[int, float], lock: threading.Lock):
        super().__init__(maxsize=maxsize)
        self._started = started
        self._started_lock = lock

    def get(self, block=True, timeout=None):
        item = super().get(block=block, timeout=timeout)
        if isinstance(item, tuple) and len(item) > 3:
            with self._started_lock:
                self._started[int(item[3] or 0)] = time.perf_counter()
        return item


class _ReplayReadyQueue(queue.Queue):
    def __init__(
        self,
        maxsize: int,
        runtime: ReplayPlaybackRuntime,
        started: dict[int, float],
        lock: threading.Lock,
        trace: Callable[[str, Mapping[str, object]], object],
        emits_preprocess_trace: bool,
    ) -> None:
        super().__init__(maxsize=maxsize)
        self._runtime = runtime
        self._started = started
        self._started_lock = lock
        self._trace = trace
        self._emits_preprocess_trace = bool(emits_preprocess_trace)

    def put(self, item, block=True, timeout=None):
        queue_started_at = time.perf_counter()
        result = super().put(item, block=block, timeout=timeout)
        if self._emits_preprocess_trace or not isinstance(item, tuple):
            return result
        sequence = int(item[3] if len(item) > 3 else 0)
        result_fields = item[4] if len(item) > 4 and isinstance(item[4], Mapping) else {}
        metadata = item[5] if len(item) > 5 and isinstance(item[5], Mapping) else {}
        with self._started_lock:
            started_at = self._started.pop(sequence, queue_started_at)
        self._trace_safely(
            "tts_preprocess",
            {
                "trace_id": self._runtime.replay_id,
                "duration_ms": round(
                    max(0.0, (time.perf_counter() - started_at) * 1000.0),
                    3,
                ),
                "queue_wait_ms": round(
                    max(0.0, (time.perf_counter() - queue_started_at) * 1000.0),
                    3,
                ),
                "elapsed_ms": round(
                    max(0.0, (time.monotonic() - self._runtime.started_at) * 1000.0),
                    3,
                ),
                "sequence": sequence,
                "replay": True,
                "replay_index": int(metadata.get("replay_index", 0) or 0),
                "kind": str(result_fields.get("kind", "") or ""),
                "outcome": "ok",
            },
        )
        return result

    def _trace_safely(self, event: str, fields: Mapping[str, object]) -> None:
        try:
            self._trace(str(event), dict(fields))
        except BaseException:
            pass


class ReplayPlaybackPipeline:
    """Bridge owned speech preparation into the Task 14 playback callback path."""

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        capabilities: ReplayPlaybackPipelineCapabilities,
    ) -> None:
        self._workers = workers
        self._capabilities = capabilities

    def prepare(
        self,
        source,
        runtime: ReplayPlaybackRuntime,
        token,
    ) -> ReplayPlaybackPreparation:
        maxsize = max(
            1,
            min(64, int(runtime.config.get("tts_prepare_buffer_chunks", 6) or 6)),
        )
        started: dict[int, float] = {}
        started_lock = threading.Lock()
        source_queue = _ReplaySourceQueue(maxsize, started, started_lock)
        ready_queue = _ReplayReadyQueue(
            maxsize,
            runtime,
            started,
            started_lock,
            self._capabilities.trace,
            self._capabilities.emits_preprocess_trace,
        )
        try:
            session = self._capabilities.open_session(runtime, source_queue, ready_queue)
        except BaseException:
            token.cancel("replay_pipeline_setup_failed")
            source.cancel("replay_pipeline_setup_failed")
            source.close()
            raise
        handles = []
        start_gate = threading.Event()

        def put_unless_cancelled(target, item) -> bool:
            while not token.cancelled:
                try:
                    target.put(item, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def bridge(worker_token) -> None:
            start_gate.wait()
            if token.cancelled or worker_token.cancelled:
                return
            try:
                while not token.cancelled and not worker_token.cancelled:
                    handoff = source.next_ready(timeout=0.05)
                    if handoff is None:
                        if source.done or source.cancelled or source.failure is not None:
                            return
                        continue
                    prepared = getattr(handoff, "chunk", handoff)
                    metadata = dict(getattr(prepared, "source_metadata", {}) or {})
                    item = (
                        str(getattr(prepared, "audio_path", "") or ""),
                        str(getattr(prepared, "expression", "") or ""),
                        str(getattr(prepared, "text", "") or ""),
                        int(getattr(prepared, "index", 0) or 0),
                        metadata,
                    )
                    if not put_unless_cancelled(source_queue, item):
                        self._delete_item(item)
                        return
            finally:
                put_unless_cancelled(source_queue, None)

        def preprocess(_worker_token) -> None:
            start_gate.wait()
            if token.cancelled or _worker_token.cancelled:
                return
            try:
                session.preprocess()
            finally:
                put_unless_cancelled(ready_queue, None)

        start_lock = threading.Lock()
        started = False

        close_lock = threading.Lock()
        closed = False

        def cancel_preparation() -> None:
            token.cancel("replay_playback_cancelled")
            source.cancel("replay_playback_cancelled")
            start_gate.set()
            self._workers.cancel_handles(tuple(handles), "replay_playback_cancelled")
            session.cancel()

        def close_preparation() -> None:
            token.cancel("replay_playback_closed")
            source.cancel("replay_playback_closed")
            start_gate.set()
            self._workers.cancel_handles(tuple(handles), "replay_playback_closed")

        def close() -> None:
            nonlocal closed
            with close_lock:
                if closed:
                    return
                closed = True
            source.close()
            session.close()

        stream = QueuePlaybackStream(
            ready_queue,
            runtime.lease,
            session.playback_callback,
            cancel_preparation=cancel_preparation,
            close_preparation=close_preparation,
            producer_threads=tuple(handle.thread for handle in handles),
            cleanup_sources=(source_queue,),
            cleanup_item=self._delete_item,
            speech_id=str(getattr(source, "speech_id", "") or ""),
            close_callback=close,
            skip_current_message=session.skip_current_message,
        )

        def start(route_effect_owner: RouteEffectOwner) -> CommandResult[None]:
            nonlocal started
            with start_lock:
                if started:
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "replay_pipeline_started",
                            "Replay pipeline workers are already started.",
                        ),
                    )
                started = True
            preprocess_result = spawn_route_worker(
                self._workers,
                route_effect_owner,
                name="nc-replay-preprocess",
                lease=runtime.lease,
                target=lambda worker_token, _owner: preprocess(worker_token),
            )
            if preprocess_result.accepted and preprocess_result.value is not None:
                handles.append(preprocess_result.value)
            bridge_result = spawn_route_worker(
                self._workers,
                route_effect_owner,
                name="nc-replay-speech-bridge",
                lease=runtime.lease,
                target=lambda worker_token, _owner: bridge(worker_token),
            )
            if bridge_result.accepted and bridge_result.value is not None:
                handles.append(bridge_result.value)
            failure = preprocess_result.failure or bridge_result.failure
            if (
                not preprocess_result.accepted
                or preprocess_result.value is None
                or not bridge_result.accepted
                or bridge_result.value is None
                or not stream.bind_producer_threads(
                    tuple(handle.thread for handle in handles)
                )
            ):
                token.cancel("replay_pipeline_start_failed")
                source.cancel("replay_pipeline_start_failed")
                start_gate.set()
                self._workers.cancel_handles(
                    tuple(handles),
                    "replay_pipeline_start_failed",
                )
                session.cancel()
                return CommandResult(
                    False,
                    failure=failure
                    or RuntimeFailure(
                        "route_effect_stale",
                        "Replay pipeline lost route authority before worker start.",
                    ),
                )
            start_gate.set()
            return CommandResult(True)
        transferred = runtime.controller_registry.transfer(
            runtime.setup,
            session.registration,
        )
        if not transferred.accepted:
            token.cancel("replay_setup_transfer_failed")
            source.cancel("replay_setup_transfer_failed")
            start_gate.set()
            self._workers.cancel_handles(tuple(handles), "replay_setup_transfer_failed")
            stream.close()
            raise ControllerSetupFailure(
                transferred.failure
                or RuntimeFailure(
                    "controller_setup_stale",
                    "The exact replay setup could not transfer to its stream.",
                )
            )
        return ReplayPlaybackPreparation(
            stream=stream,
            registration=session.registration,
            start=start,
        )

    def _delete_item(self, item: object) -> None:
        path = ""
        if isinstance(item, tuple) and item:
            path = str(item[0] or "")
        else:
            path = str(getattr(item, "audio_path", "") or "")
        if not path:
            return
        try:
            self._capabilities.delete_audio(path)
        except BaseException:
            pass


@dataclass(frozen=True, slots=True)
class LegacyPlaybackDeviceAdapter:
    play_file: Callable[..., object]

    def play(self, path: str, *, stop_event: object, volume: float) -> object:
        return self.play_file(path, stop_event=stop_event, volume=volume)


@dataclass(frozen=True, slots=True)
class LegacyPlaybackEffectsCapabilities:
    admit_route_effect: Callable[[WorkLease], object | None]
    audio_segment: object
    audio_playing: object
    avatar_gui: object
    clear_avatar_stream_state: Callable[..., object]
    device: LegacyPlaybackDeviceAdapter
    dry_run: object
    env_flag: Callable[..., object]
    estimate_displayed_frames: Callable[..., object]
    is_musetalk_avatar: Callable[..., object]
    lease_is_current: Callable[[WorkLease], bool]
    list_png_frames: Callable[..., object]
    log_musetalk_memory_checkpoint: Callable[..., object]
    manual_pause_active: object
    maybe_transition_avatar_default: Callable[..., object]
    musetalk_state: object
    notify_segment_started: Callable[..., object]
    pause_after_chunk: object
    playback_paused: object
    playback_service: object
    play_story_audio_cues: Callable[..., object]
    presence_set_audio_level: Callable[..., object]
    presence_set_mood: Callable[..., object]
    presence_set_state: Callable[..., object]
    prime_preview_frame: Callable[..., object]
    record_latency: Callable[..., object]
    release_route_effect: Callable[[object], object]
    safe_delete: Callable[..., object]
    save_seam_debug_images: Callable[..., object]
    schedule_runtime_cleanup: Callable[..., object]
    soundfile: object
    stop_flag: object
    stop_playback: object
    stop_preview_idle_stream: Callable[..., object]
    stream_audio_progress: Callable[..., object]
    stream_preview_frames: Callable[..., object]
    transition_to_local_idle: Callable[..., object]
    tts_controller_stop_event: Callable[..., object]
    tts_duck_end: Callable[..., object]
    tts_duck_start: Callable[..., object]
    tts_playback_volume: Callable[..., object]
    unregister_controller: Callable[..., object]
    workers: Callable[[], WorkerSupervisor]
    first_chunk_predicted_delay_seconds: float
    stream_first_chunk_idle_sync_max_seconds: float
    stream_first_chunk_plan_sync_max_seconds: float


def _publish_legacy_terminal_chunk_state(
    musetalk_state,
    kind,
    chunk_result,
    chunk_sequence,
    pipeline_reply_id,
):
    musetalk_state.update_musetalk_pipeline_chunk(
        int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
        reply_id=pipeline_reply_id,
        playback_state="completed",
        audio_finished_at=time.time(),
    )
    if kind == "musetalk":
        print(f"⏹️ [MuseTalk] Finished chunk {chunk_result.get('chunk_id')}")
        return time.time()

    if kind == "scenic":
        preview_frame_index = 0
    else:
        preview_frame_index = max(
            0,
            int(chunk_result.get("expected_frame_count", 0) or 0) - 1,
        )
    musetalk_state.update_current_musetalk_frame_data(
        preview_frame_index=preview_frame_index,
        preview_source_index=preview_frame_index,
    )
    if kind == "scenic":
        final_frame_paths = list(chunk_result.get("frame_paths", []) or [])
        if final_frame_paths:
            musetalk_state.write_musetalk_preview_frame(
                {
                    "chunk_id": chunk_result.get("chunk_id"),
                    "frame_path": final_frame_paths[0],
                    "frame_index": 0,
                    "source_index": 0,
                    "fps": max(1, int(chunk_result.get("fps", 1) or 1)),
                    "status": "ready",
                    "loop": False,
                    "emitted_at": time.time(),
                    "avatar_id": chunk_result.get("avatar_id") or "scenic",
                    "scenic_tag": chunk_result.get("scenic_tag"),
                    "force_repaint": True,
                }
            )
    if kind == "scenic":
        print(f"⏹️ [Scenic] Finished delegated chunk {chunk_result.get('chunk_id')}")
    else:
        print(f"⏹️ [None] Finished audio-only chunk {chunk_result.get('chunk_id')}")
    return time.time()


class LegacyPlaybackEffectsAdapter:
    """Own legacy playback effects while callers only prepare and enqueue."""

    accepts_route_effect_owner = True

    def __init__(
        self,
        capabilities: LegacyPlaybackEffectsCapabilities,
        *,
        controller: object,
        avatar_mode: str,
        turn_config: object,
        pipeline_telemetry_enabled: bool,
        pipeline_reply_id: object,
        playback_queue: object,
        ready_for_playback: object,
        replay_mode: bool,
        dry_run_reply_id: object,
        latency_trace_id: str,
        speak_started_at: float,
        queue_story_visual_reply: Callable[..., object],
        pipeline_stopping: Callable[[], bool],
        retire_controller_on_completion: bool = True,
    ) -> None:
        self._capabilities = capabilities
        self._controller = controller
        self._avatar_mode = avatar_mode
        self._turn_config = turn_config
        self._pipeline_telemetry_enabled = pipeline_telemetry_enabled
        self._pipeline_reply_id = pipeline_reply_id
        self._playback_queue = playback_queue
        self._ready_for_playback = ready_for_playback
        self._replay_mode = replay_mode
        self._dry_run_reply_id = dry_run_reply_id
        self._latency_trace_id = latency_trace_id
        self._speak_started_at = speak_started_at
        self._queue_story_visual_reply = queue_story_visual_reply
        self._pipeline_stopping = pipeline_stopping
        self._retire_controller_on_completion = bool(
            retire_controller_on_completion
        )

    def __call__(
        self,
        playback_chunks,
        service_stop_event,
        playback_owner,
        route_effect_owner,
    ):
        if (
            not isinstance(route_effect_owner, RouteEffectOwner)
            or not route_effect_owner.matches_playback_owner(playback_owner)
        ):
            return None
        result = route_effect_owner.run_step(
            "playback_callback",
            lambda: self._run_owned(
                playback_chunks,
                service_stop_event,
                playback_owner,
                route_effect_owner,
            ),
        )
        if self._retire_controller_on_completion:
            self._capabilities.unregister_controller(self._controller)
        return result.value if result.accepted else None

    def _run_owned(
        self,
        playback_chunks,
        service_stop_event,
        playback_owner,
        route_effect_owner,
    ):
        capabilities = self._capabilities
        AudioSegment = capabilities.audio_segment
        MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS = capabilities.first_chunk_predicted_delay_seconds
        STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS = capabilities.stream_first_chunk_idle_sync_max_seconds
        STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS = capabilities.stream_first_chunk_plan_sync_max_seconds
        _env_flag = capabilities.env_flag
        _is_musetalk_avatar_adapter = capabilities.is_musetalk_avatar
        _notify_addon_tts_duck_end = capabilities.tts_duck_end
        _notify_addon_tts_duck_start = capabilities.tts_duck_start
        _notify_addon_tts_segment_started = capabilities.notify_segment_started
        _play_addon_story_audio_cues = capabilities.play_story_audio_cues
        _playback_service = capabilities.playback_service
        _presence_set_audio_level = capabilities.presence_set_audio_level
        _presence_set_mood = capabilities.presence_set_mood
        _presence_set_state = capabilities.presence_set_state
        _record_tts_latency_event = capabilities.record_latency
        _tts_controller_playback_stop_event = capabilities.tts_controller_stop_event
        _tts_playback_voice_volume = capabilities.tts_playback_volume
        _unregister_active_tts_controller = capabilities.unregister_controller
        audio_playing = capabilities.audio_playing
        avatar_gui = capabilities.avatar_gui
        clear_avatar_stream_state = capabilities.clear_avatar_stream_state
        dry_run = capabilities.dry_run
        estimate_displayed_musetalk_frames = capabilities.estimate_displayed_frames
        list_png_frames = capabilities.list_png_frames
        log_musetalk_memory_checkpoint = capabilities.log_musetalk_memory_checkpoint
        manual_pause_active = capabilities.manual_pause_active
        maybe_transition_musetalk_avatar_back_to_default = capabilities.maybe_transition_avatar_default
        musetalk_state = capabilities.musetalk_state
        pause_after_chunk = capabilities.pause_after_chunk
        playback_paused = capabilities.playback_paused
        prime_musetalk_preview_frame = capabilities.prime_preview_frame
        replay_mode = self._replay_mode
        safe_delete_with_retry = capabilities.safe_delete
        save_musetalk_seam_debug_images = capabilities.save_seam_debug_images
        schedule_musetalk_runtime_cleanup = capabilities.schedule_runtime_cleanup
        sf = capabilities.soundfile
        stop_flag = capabilities.stop_flag
        stop_playback = capabilities.stop_playback
        stop_ua_companion_orb_musetalk_idle_stream = capabilities.stop_preview_idle_stream
        stream_delegated_audio_progress = capabilities.stream_audio_progress
        stream_musetalk_preview_frames = capabilities.stream_preview_frames
        transition_musetalk_to_local_idle = capabilities.transition_to_local_idle
        avatar_mode = self._avatar_mode
        ctrl = self._controller
        dry_run_reply_id = self._dry_run_reply_id
        latency_trace_id = self._latency_trace_id
        pipeline_reply_id = self._pipeline_reply_id
        pipeline_telemetry_enabled = self._pipeline_telemetry_enabled
        playback_queue = self._playback_queue
        ready_for_playback = self._ready_for_playback
        speak_started_at = self._speak_started_at
        turn_config = self._turn_config
        _pipeline_stopping = self._pipeline_stopping
        _queue_story_visual_reply = self._queue_story_visual_reply
        workers = capabilities.workers()
        play_audio_file = capabilities.device.play
        last_resumed_at = _playback_service.last_resumed_at()
        last_resume_requested_at = _playback_service.resume_requested_at()
        playback_lease = playback_owner.lease
        stale_effect_discarded = False

        def record_stale_effect_discard(
            effect_name: str,
            failure_category: str,
        ) -> None:
            nonlocal stale_effect_discarded
            if stale_effect_discarded:
                return
            stale_effect_discarded = True
            _record_tts_latency_event(
                "tts_playback_effect_discard",
                trace_id=latency_trace_id,
                outcome="discarded",
                failure_category=failure_category,
                effect=str(effect_name or "terminal_effect"),
                owner_generation=playback_owner.generation,
            )

        def run_route_effect(effect_name, operation, *args, **kwargs):
            result = route_effect_owner.run_step(
                str(effect_name or "terminal_effect"),
                lambda: operation(*args, **kwargs),
            )
            if not result.accepted:
                failure = result.failure
                record_stale_effect_discard(
                    effect_name,
                    (
                        failure.category
                        if failure is not None
                        else "route_effect_stale"
                    ),
                )
                return False, None
            return True, result.value

        retire_controller_on_completion = self._retire_controller_on_completion
        if _pipeline_stopping():
            if retire_controller_on_completion:
                ctrl.done.set()
            return
        admitted, _unused = run_route_effect(
            "audio_playing_start",
            audio_playing.set,
        )
        if not admitted:
            if retire_controller_on_completion:
                ctrl.done.set()
            return
        if avatar_gui:
            run_route_effect(
                "avatar_speaking_start",
                avatar_gui.set_speaking_state,
                True,
            )
        last_chunk_end_time = None
        tts_duck_active = False
        first_playback_traced = False

        def start_tts_duck_once(chunk_result=None, source_meta=None, text="", emotion=""):
            nonlocal tts_duck_active
            if tts_duck_active:
                return
            payload = {
                "source": "tts_playback",
                "text": str(text or ""),
                "emotion": str(emotion or ""),
                "chunk_id": (chunk_result or {}).get("chunk_id") if isinstance(chunk_result, dict) else "",
                "sequence_index": int((chunk_result or {}).get("sequence_index", 0) or 0) if isinstance(chunk_result, dict) else 0,
                "persona_id": str((source_meta or {}).get("persona_id", "") or ""),
                "display_name": str((source_meta or {}).get("display_name", "") or ""),
            }
            try:
                admitted, result = run_route_effect(
                    "tts_duck_start",
                    _notify_addon_tts_duck_start,
                    payload,
                )
                tts_duck_active = bool(result) if admitted else False
            except Exception:
                tts_duck_active = False

        def end_tts_duck(reason="completed"):
            nonlocal tts_duck_active
            if not tts_duck_active:
                return
            try:
                run_route_effect(
                    "tts_duck_end",
                    _notify_addon_tts_duck_end,
                    {"source": "tts_playback", "reason": str(reason or "completed")},
                )
            except Exception:
                pass
            tts_duck_active = False

        try:
            for playback_chunk in playback_chunks:
                item = playback_chunk.payload
                if (
                    service_stop_event.is_set()
                    or stop_playback.is_set()
                    or ctrl.cancel_requested.is_set()
                ):
                    safe_delete_with_retry(item[0])
                    break
                while (
                    playback_paused.is_set()
                    and not service_stop_event.is_set()
                    and not stop_playback.is_set()
                    and not ctrl.cancel_requested.is_set()
                ):
                    time.sleep(0.05)

                if not isinstance(item, tuple):
                    continue

                if len(item) >= 6:
                    path, emotion, txt, chunk_sequence, chunk_result, source_meta = item
                else:
                    path, emotion, txt, chunk_sequence, chunk_result = item
                    source_meta = {}
                replay_message_id = str((source_meta or {}).get("replay_message_id", "") or "")
                if ctrl.cancel_requested.is_set() or stop_playback.is_set():
                    safe_delete_with_retry(path)
                    continue
                if replay_message_id:
                    ctrl.clear_skip_current_message_if_new(replay_message_id)
                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue
                    ctrl.set_current_message_id(replay_message_id)
                    if bool((source_meta or {}).get("replay_message_first_chunk", False)):
                        replay_index = int((source_meta or {}).get("replay_index", 0) or 0)
                        replay_total = int((source_meta or {}).get("replay_total", 0) or 0)
                        if replay_index and replay_total:
                            print(f"🔁 Replaying chat session message {replay_index}/{max(replay_total, 1)}...")
                kind = chunk_result.get("kind", "audio")
                try:
                    chunk_duration_seconds = float(sf.info(path).duration or 0.0)
                except Exception:
                    chunk_duration_seconds = 0.0
                run_route_effect(
                    "presence_mood",
                    _presence_set_mood,
                    emotion,
                )

                if kind == "musetalk":
                    current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                    previous_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                    frame_dir = chunk_result.get("frame_dir", "")
                    fps = int(chunk_result.get("fps", turn_config.get("musetalk_fps", 24)) or 24)
                    ready_event = chunk_result.get("ready_event")
                    result_holder = chunk_result.get("result_holder", {})
                    if result_holder.get("cancelled"):
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="cancelled",
                            playback_state="cancelled",
                        )
                        safe_delete_with_retry(path)
                        continue
                    if _is_musetalk_avatar_adapter(avatar_gui):
                        chunk_generation = int(result_holder.get("generation", -1))
                        if chunk_generation != int(getattr(avatar_gui, "reply_generation", chunk_generation)):
                            musetalk_state.update_musetalk_pipeline_chunk(
                                current_sequence,
                                reply_id=pipeline_reply_id,
                                status="cancelled",
                                playback_state="cancelled",
                            )
                            safe_delete_with_retry(path)
                            continue
                    trim_start_frames = int(result_holder.get("trim_start_frames", 0) or 0)
                    is_first_reply_chunk = bool(chunk_result.get("sequence_index") == 0)
                    stream_fast_start = bool(turn_config.get("stream_mode", False))
                    if is_first_reply_chunk and stream_fast_start:
                        min_buffer_frames = max(10, min(int(fps * 0.5), 16))
                        musetalk_state.append_musetalk_preview_log(
                            f"🌊 [Stream] First chunk fast-start gate {chunk_result.get('chunk_id')}: "
                            f"min_buffer_frames={min_buffer_frames}"
                        )
                    elif is_first_reply_chunk:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    else:
                        min_buffer_frames = max(24, min(int(fps * 2.5), 72))
                    if is_first_reply_chunk:
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            startup_buffer_frames=min_buffer_frames,
                        )
                    wait_start = time.time()
                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk buffer wait start {chunk_result.get('chunk_id')}: "
                            f"min_buffer_frames={min_buffer_frames}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_buffer_wait_start",
                            chunk_result.get("chunk_id"),
                            {"min_buffer_frames": min_buffer_frames},
                        )
                    try:
                        frame_paths = list_png_frames(frame_dir)
                    except FileNotFoundError:
                        frame_paths = []

                    while (
                        len(frame_paths) < min_buffer_frames
                        and ready_event is not None
                        and not ready_event.is_set()
                        and not stop_playback.is_set()
                        and not ctrl.cancel_requested.is_set()
                        and not ctrl.should_skip_message(replay_message_id)
                        and time.time() - wait_start < 60
                    ):
                        time.sleep(0.1)
                        try:
                            frame_paths = list_png_frames(frame_dir)
                        except FileNotFoundError:
                            frame_paths = []
                        if result_holder.get("cancelled"):
                            break

                    if result_holder.get("cancelled"):
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="cancelled",
                            playback_state="cancelled",
                        )
                        safe_delete_with_retry(path)
                        continue

                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue

                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk buffer wait done {chunk_result.get('chunk_id')}: "
                            f"waited_ms={(time.time() - wait_start) * 1000.0:.1f} "
                            f"buffered={len(frame_paths)} ready_event={bool(ready_event and ready_event.is_set())}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_buffer_wait_done",
                            chunk_result.get("chunk_id"),
                            {
                                "buffered": len(frame_paths),
                                "ready_event": bool(ready_event and ready_event.is_set()),
                            },
                        )
                        dry_run.record_reply_metric(
                            dry_run_reply_id,
                            "first_chunk_buffer_wait_ms",
                            round((time.time() - wait_start) * 1000.0, 1),
                        )

                    if not frame_paths and ready_event is not None and ready_event.is_set():
                        try:
                            frame_paths = list_png_frames(frame_dir)
                        except FileNotFoundError:
                            frame_paths = []

                    if trim_start_frames > 0 and frame_paths:
                        trimmed_paths = frame_paths[min(trim_start_frames, len(frame_paths) - 1):]
                        if trimmed_paths:
                            frame_paths = trimmed_paths

                    if (
                        not frame_paths
                        and ready_event is not None
                        and not ready_event.is_set()
                        and not stop_playback.is_set()
                        and not ctrl.cancel_requested.is_set()
                        and not ctrl.should_skip_message(replay_message_id)
                    ):
                        while (
                            not frame_paths
                            and ready_event is not None
                            and not ready_event.is_set()
                            and not stop_playback.is_set()
                            and not ctrl.cancel_requested.is_set()
                            and not ctrl.should_skip_message(replay_message_id)
                        ):
                            time.sleep(0.1)
                            try:
                                frame_paths = list_png_frames(frame_dir)
                            except FileNotFoundError:
                                frame_paths = []
                        if trim_start_frames > 0 and frame_paths:
                            trimmed_paths = frame_paths[min(trim_start_frames, len(frame_paths) - 1):]
                            if trimmed_paths:
                                frame_paths = trimmed_paths

                    if ctrl.should_skip_message(replay_message_id):
                        safe_delete_with_retry(path)
                        continue

                    if not frame_paths:
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            status="failed",
                            playback_state="failed",
                        )
                        print(
                            f"⚠️ [MuseTalk] No buffered frames for chunk {chunk_result.get('chunk_id')} "
                            f"(dir={frame_dir}, result_frames={result_holder.get('frame_count')})"
                        )
                        safe_delete_with_retry(path)
                        continue

                    visible_start_index = int(result_holder.get("start_index", 0) or 0)
                    live_previous_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                    previous_avatar_id = live_previous_state.get("avatar_id", previous_state.get("avatar_id"))
                    current_avatar_id = chunk_result.get("avatar_id")
                    previous_status = live_previous_state.get("status", previous_state.get("status"))
                    previous_chunk_id = live_previous_state.get("chunk_id", previous_state.get("chunk_id"))
                    previous_start_index = int(live_previous_state.get("start_index", previous_state.get("start_index", 0)) or 0)
                    if (
                        current_avatar_id == previous_avatar_id
                        and previous_status == "ready"
                        and previous_chunk_id
                    ):
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        preview_source_index = live_previous_state.get("preview_source_index")
                        if preview_chunk_id == previous_chunk_id and preview_source_index is not None:
                            visible_start_index = int(preview_source_index) + 1
                        else:
                            previous_displayed_frames = estimate_displayed_musetalk_frames(live_previous_state)
                            visible_start_index = previous_start_index + previous_displayed_frames
                    elif (
                        bool(chunk_result.get("sequence_index") == 0)
                        and previous_status == "idle"
                        and previous_chunk_id
                        and str(previous_chunk_id).startswith("first_chunk_plan:")
                    ):
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        preview_source_index = live_previous_state.get("preview_source_index")
                        if preview_chunk_id == previous_chunk_id and preview_source_index is not None:
                            try:
                                target_entry_index = int(visible_start_index)
                                wait_started_at = time.time()
                                max_wait_seconds = first_chunk_plan_sync_wait_seconds(
                                    stream=bool(turn_config.get("stream_mode", False)),
                                    predicted_delay=MUSE_FIRST_CHUNK_PREDICTED_DELAY_SECONDS,
                                )
                                while (
                                    not stop_flag.is_set()
                                    and (time.time() - wait_started_at) < max_wait_seconds
                                ):
                                    live_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                                    if live_state.get("chunk_id") != previous_chunk_id:
                                        break
                                    live_preview_source = live_state.get("preview_source_index")
                                    if live_preview_source is None:
                                        time.sleep(0.01)
                                        continue
                                    live_preview_source = int(live_preview_source)
                                    if live_preview_source == target_entry_index:
                                        visible_start_index = target_entry_index
                                        break
                                    time.sleep(0.01)
                                musetalk_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk plan sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(musetalk_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
                                    f"waited_ms={(time.time() - wait_started_at) * 1000.0:.1f}"
                                )
                                log_musetalk_memory_checkpoint(
                                    "first_chunk_plan_sync",
                                    chunk_result.get("chunk_id"),
                                    {
                                        "target": target_entry_index,
                                        "final_preview": getattr(musetalk_state, "current_musetalk_frame_data", {}).get("preview_source_index"),
                                    },
                                )
                                dry_run.record_reply_metric(
                                    dry_run_reply_id,
                                    "first_chunk_plan_sync_ms",
                                    round((time.time() - wait_started_at) * 1000.0, 1),
                                )
                            except Exception:
                                pass
                    elif (
                        bool(chunk_result.get("sequence_index") == 0)
                        and previous_status == "idle"
                        and previous_chunk_id == "idle"
                    ):
                        preview_source_index = live_previous_state.get("preview_source_index")
                        preview_chunk_id = live_previous_state.get("preview_chunk_id")
                        if preview_chunk_id == "idle" and preview_source_index is not None:
                            try:
                                target_entry_index = int(visible_start_index)
                                wait_started_at = time.time()
                                if bool(turn_config.get("stream_mode", False)):
                                    max_wait_seconds = STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS
                                else:
                                    max_wait_seconds = max(0.25, min(1.5, abs(target_entry_index - int(preview_source_index)) / max(fps, 1) + 0.25))
                                while (
                                    not stop_flag.is_set()
                                    and (time.time() - wait_started_at) < max_wait_seconds
                                ):
                                    live_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                                    if live_state.get("chunk_id") != "idle":
                                        break
                                    live_preview_source = live_state.get("preview_source_index")
                                    if live_preview_source is None:
                                        time.sleep(0.01)
                                        continue
                                    live_preview_source = int(live_preview_source)
                                    if live_preview_source == target_entry_index:
                                        visible_start_index = target_entry_index
                                        break
                                    time.sleep(0.01)
                                musetalk_state.append_musetalk_preview_log(
                                    f"🕒 [MuseTalkStartup] First chunk idle sync {chunk_result.get('chunk_id')}: "
                                    f"target={target_entry_index} final_preview={getattr(musetalk_state, 'current_musetalk_frame_data', {}).get('preview_source_index')} "
                                    f"waited_ms={(time.time() - wait_started_at) * 1000.0:.1f}"
                                )
                                dry_run.record_reply_metric(
                                    dry_run_reply_id,
                                    "first_chunk_idle_sync_ms",
                                    round((time.time() - wait_started_at) * 1000.0, 1),
                                )
                            except Exception:
                                pass

                    raw_expected_frame_count = max(
                        len(frame_paths),
                        int(round(chunk_duration_seconds * max(fps, 1))),
                        int(result_holder.get("frame_count", 0) or 0),
                    )
                    expected_frame_count = max(
                        len(frame_paths),
                        max(raw_expected_frame_count - trim_start_frames, 0),
                    )
                    duration_seconds = max(
                        chunk_duration_seconds,
                        max(expected_frame_count - 1, 0) / max(fps, 1),
                    )
                    publish_time = time.time()
                    if (
                        dry_run_reply_id
                        and int(chunk_result.get("sequence_index", 0) or 0) > 0
                        and live_previous_state.get("chunk_id")
                    ):
                        previous_audio_started_at = live_previous_state.get("audio_started_at")
                        previous_duration_seconds = float(live_previous_state.get("duration_seconds", 0.0) or 0.0)
                        if previous_audio_started_at and previous_duration_seconds > 0:
                            followup_headroom_ms = (
                                (float(previous_audio_started_at) + previous_duration_seconds) - publish_time
                            ) * 1000.0
                            dry_run.accumulate_reply_metric(
                                dry_run_reply_id,
                                "followup_headroom_sum_ms",
                                round(followup_headroom_ms, 1),
                            )
                            dry_run.accumulate_reply_metric(
                                dry_run_reply_id,
                                "followup_headroom_count",
                                1,
                            )
                            dry_run.update_reply_min_metric(
                                dry_run_reply_id,
                                "min_followup_headroom_ms",
                                round(followup_headroom_ms, 1),
                            )

                    musetalk_state.set_current_musetalk_frame_data({
                        "frame_paths": frame_paths,
                        "frame_dir": frame_dir,
                        "fps": fps,
                        "sync_time": publish_time,
                        "duration_seconds": duration_seconds,
                        "expected_frame_count": expected_frame_count,
                        "trim_start_frames": trim_start_frames,
                        "chunk_id": chunk_result.get("chunk_id"),
                        "text": txt,
                        "status": "ready",
                        "loop": False,
                        "start_index": visible_start_index,
                        "frame_count": expected_frame_count,
                        "avatar_id": chunk_result.get("avatar_id"),
                        "sequence_index": chunk_result.get("sequence_index"),
                        "is_first_reply_chunk": bool(chunk_result.get("sequence_index") == 0),
                        "published_at": publish_time,
                        "preview_chunk_id": None,
                        "preview_frame_index": -1,
                        "preview_source_index": None,
                    })
                    musetalk_state.update_musetalk_pipeline_chunk(
                        current_sequence,
                        reply_id=pipeline_reply_id,
                        playback_state="buffered",
                        duration_seconds=duration_seconds,
                        expected_frame_count=expected_frame_count,
                        chunk_id=chunk_result.get("chunk_id"),
                    )
                    dry_run.record_reply_event(dry_run_reply_id, "first_chunk_published_at")
                    dry_run.record_reply_metric(dry_run_reply_id, "first_chunk_start_index", visible_start_index)
                    dry_run.record_reply_metric(dry_run_reply_id, "first_chunk_expected_frames", expected_frame_count)
                    startup_resume_ms = None
                    if last_resumed_at and (time.time() - last_resumed_at) < 30.0:
                        startup_resume_ms = (time.time() - last_resumed_at) * 1000.0
                    prime_musetalk_preview_frame(musetalk_state.current_musetalk_frame_data)
                    save_musetalk_seam_debug_images(previous_state, musetalk_state.current_musetalk_frame_data)
                    run_route_effect(
                        "runtime_cleanup",
                        schedule_musetalk_runtime_cleanup,
                        keep_frame_dirs=[frame_dir],
                        work_lease=playback_lease,
                        route_effect_owner=route_effect_owner,
                    )
                    print(
                        f"✅ [MuseTalk] Initial buffer {len(frame_paths)} frame(s): {txt[:20]}... "
                        f"(chunk={chunk_result.get('chunk_id')}, start_index={visible_start_index}, trim={trim_start_frames})"
                    )
                    if startup_resume_ms is not None:
                        message = (
                            f"🕒 [MuseTalkStartup] Resume -> initial buffer {chunk_result.get('chunk_id')}: "
                            f"{startup_resume_ms:.1f} ms"
                        )
                        print(message)
                        musetalk_state.append_musetalk_preview_log(message)
                    if is_first_reply_chunk:
                        musetalk_state.append_musetalk_preview_log(
                            f"🕒 [MuseTalkStartup] First chunk published {chunk_result.get('chunk_id')}: "
                            f"buffered={len(frame_paths)} expected={expected_frame_count} "
                            f"start_index={visible_start_index}"
                        )
                        log_musetalk_memory_checkpoint(
                            "first_chunk_published",
                            chunk_result.get("chunk_id"),
                            {
                                "buffered": len(frame_paths),
                                "expected": expected_frame_count,
                                "start_index": visible_start_index,
                            },
                        )
                    print(
                        f"▶️ [MuseTalk] Playing chunk {chunk_result.get('chunk_id')} "
                        f"(initial buffer {len(frame_paths)} frame(s), ~{len(frame_paths) / max(fps, 1):.2f}s ready)"
                    )
                    time.sleep(0.01)
                elif kind in {"none", "scenic"}:
                    delegated_label = {"none": "None", "scenic": "Scenic"}.get(kind, kind)
                    current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                    delegated_duration_seconds = max(
                        0.0,
                        float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                    )
                    expected_frame_count = max(
                        2,
                        int(chunk_result.get("expected_frame_count", 0) or 0),
                        int(round(delegated_duration_seconds * 50.0)) if delegated_duration_seconds > 0 else 2,
                    )
                    delegated_frame_paths = list(chunk_result.get("frame_paths", []) or [])
                    delegated_frame_dir = str(chunk_result.get("frame_dir", "") or "")
                    delegated_fps = max(1, int(chunk_result.get("fps", 50) or 50))
                    if kind != "none":
                        musetalk_state.set_current_musetalk_frame_data({
                            "frame_paths": delegated_frame_paths,
                            "frame_dir": delegated_frame_dir,
                            "fps": delegated_fps,
                            "sync_time": 0.0,
                            "duration_seconds": delegated_duration_seconds,
                            "expected_frame_count": expected_frame_count,
                            "trim_start_frames": 0,
                            "chunk_id": chunk_result.get("chunk_id"),
                            "text": txt,
                            "status": "ready",
                            "loop": False,
                            "start_index": 0,
                            "frame_count": expected_frame_count,
                            "sequence_index": current_sequence,
                            "preview_chunk_id": chunk_result.get("chunk_id"),
                            "preview_frame_index": 0,
                            "preview_source_index": 0,
                            "avatar_id": chunk_result.get("avatar_id") or kind,
                        })
                    if delegated_frame_paths:
                        musetalk_state.write_musetalk_preview_frame(
                            {
                                "chunk_id": chunk_result.get("chunk_id"),
                                "frame_path": delegated_frame_paths[0],
                                "frame_index": 0,
                                "source_index": 0,
                                "fps": delegated_fps,
                                "status": "ready",
                                "loop": False,
                                "emitted_at": time.time(),
                            }
                        )
                    musetalk_state.update_musetalk_pipeline_chunk(
                        current_sequence,
                        reply_id=pipeline_reply_id,
                        playback_state="buffered",
                        duration_seconds=delegated_duration_seconds,
                        expected_frame_count=expected_frame_count,
                        chunk_id=chunk_result.get("chunk_id"),
                    )
                    print(
                        f"✅ [{delegated_label}] Chunk buffered for delegated playback "
                        f"({delegated_duration_seconds:.2f}s, chunk={chunk_result.get('chunk_id')})"
                    )

                if not stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                    preview_stream_handle = None
                    skip_local_playback = bool(chunk_result.get("skip_local_playback", False))
                    delegated_playback_duration = max(
                        0.0,
                        float(chunk_result.get("playback_duration_seconds", 0.0) or 0.0),
                    )
                    story_audio_cues = list((source_meta or {}).get("story_audio_cues") or [])
                    if story_audio_cues:
                        run_route_effect(
                            "story_audio_cues",
                            _play_addon_story_audio_cues,
                            story_audio_cues,
                        )
                    if bool((source_meta or {}).get("tts_source_first_chunk", False)):
                        persona_id = str((source_meta or {}).get("persona_id", "") or "").strip()
                        if persona_id:
                            _notify_addon_tts_segment_started(
                                {
                                    "persona_id": persona_id,
                                    "display_name": str((source_meta or {}).get("display_name", "") or ""),
                                    "text": str(txt or ""),
                                    "emotion": str(emotion or ""),
                                    "voice_route": dict((source_meta or {}).get("voice_route") or {}),
                                    "chunk_id": chunk_result.get("chunk_id"),
                                    "sequence_index": int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                                }
                            )
                    start_tts_duck_once(chunk_result, source_meta, txt, emotion)
                    chunk_playback_started_at = time.perf_counter()
                    _record_tts_latency_event(
                        "tts_chunk_playback_start",
                        trace_id=latency_trace_id,
                        text=str(txt or ""),
                        elapsed_ms=round((time.monotonic() - speak_started_at) * 1000.0, 3),
                        sequence=int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                        replay=bool(replay_mode),
                        replay_index=int((source_meta or {}).get("replay_index", 0) or 0),
                        kind=str(kind or ""),
                        local_playback=not skip_local_playback,
                        duration_seconds=(
                            delegated_playback_duration
                            if delegated_playback_duration > 0.0
                            else chunk_duration_seconds
                        ),
                    )
                    if not first_playback_traced:
                        _record_tts_latency_event(
                            "tts_playback_start",
                            trace_id=latency_trace_id,
                            elapsed_ms=round((time.monotonic() - speak_started_at) * 1000.0, 3),
                            sequence=int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                            local_playback=not skip_local_playback,
                        )
                        first_playback_traced = True
                    if kind == "musetalk":
                        audio_start_time = time.time()
                        run_route_effect(
                            "story_visual_reply",
                            _queue_story_visual_reply,
                            playback_lease,
                            txt,
                            emotion,
                        )
                        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") == chunk_result.get("chunk_id"):
                            current_state["sync_time"] = audio_start_time
                            current_state["audio_started_at"] = audio_start_time
                            musetalk_state.write_musetalk_preview_snapshot(current_state)
                            run_route_effect(
                                "preview_idle_stop",
                                stop_ua_companion_orb_musetalk_idle_stream,
                                work_lease=playback_lease,
                            )
                            if not _env_flag("NC_MUSETALK_DISABLE_PREVIEW_STREAM_THREAD"):
                                preview_worker = spawn_route_worker(
                                    workers,
                                    route_effect_owner,
                                    name="nc-musetalk-preview",
                                    lease=playback_lease,
                                    target=lambda token, _owner: stream_musetalk_preview_frames(
                                        current_state,
                                        token,
                                    ),
                                )
                                if preview_worker.accepted:
                                    preview_stream_handle = preview_worker.value
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            playback_state="playing",
                            audio_started_at=audio_start_time,
                        )
                        startup_audio_ms = None
                        if last_resumed_at and (audio_start_time - last_resumed_at) < 30.0:
                            startup_audio_ms = (audio_start_time - last_resumed_at) * 1000.0
                        print(
                            f"⏱️ [MuseTalk] Audio start {chunk_result.get('chunk_id')}: "
                            f"audio={chunk_duration_seconds:.2f}s preview={float(musetalk_state.current_musetalk_frame_data.get('duration_seconds', 0.0) or 0.0):.2f}s"
                        )
                        if startup_audio_ms is not None:
                            message = (
                                f"🕒 [MuseTalkStartup] Resume -> audio start {chunk_result.get('chunk_id')}: "
                                f"{startup_audio_ms:.1f} ms"
                            )
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)
                        if is_first_reply_chunk:
                            musetalk_state.append_musetalk_preview_log(
                                f"🕒 [MuseTalkStartup] First chunk audio start {chunk_result.get('chunk_id')}: "
                                f"buffered={len(current_state.get('frame_paths', []) or [])} "
                                f"preview_duration={float(current_state.get('duration_seconds', 0.0) or 0.0):.2f}s"
                            )
                            log_musetalk_memory_checkpoint(
                                "first_chunk_audio_start",
                                chunk_result.get("chunk_id"),
                                {
                                    "buffered": len(current_state.get("frame_paths", []) or []),
                                    "preview_duration_s": round(float(current_state.get("duration_seconds", 0.0) or 0.0), 3),
                                },
                            )
                            dry_run.record_reply_event(dry_run_reply_id, "first_chunk_audio_start_at")
                            dry_run.record_reply_metric(
                                dry_run_reply_id,
                                "first_chunk_preview_duration_s",
                                round(float(current_state.get("duration_seconds", 0.0) or 0.0), 3),
                            )
                            dry_run.finalize_reply(dry_run_reply_id)
                    elif kind in {"none", "scenic"}:
                        audio_start_time = time.time()
                        run_route_effect(
                            "story_visual_reply",
                            _queue_story_visual_reply,
                            playback_lease,
                            txt,
                            emotion,
                        )
                        current_sequence = int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0)
                        current_state = getattr(musetalk_state, "current_musetalk_frame_data", {}) or {}
                        if current_state.get("chunk_id") != chunk_result.get("chunk_id"):
                            current_state = {
                                "frame_paths": list(chunk_result.get("frame_paths", []) or []),
                                "frame_dir": str(chunk_result.get("frame_dir", "") or ""),
                                "fps": max(1, int(chunk_result.get("fps", 50) or 50)),
                                "sync_time": 0.0,
                                "duration_seconds": delegated_playback_duration,
                                "expected_frame_count": max(
                                    2,
                                    int(chunk_result.get("expected_frame_count", 0) or 0),
                                    int(round(delegated_playback_duration * 50.0)) if delegated_playback_duration > 0 else 2,
                                ),
                                "trim_start_frames": 0,
                                "chunk_id": chunk_result.get("chunk_id"),
                                "text": txt,
                                "status": "ready",
                                "loop": False,
                                "start_index": 0,
                                "frame_count": max(
                                    2,
                                    int(chunk_result.get("expected_frame_count", 0) or 0),
                                    int(round(delegated_playback_duration * 50.0)) if delegated_playback_duration > 0 else 2,
                                ),
                                "sequence_index": current_sequence,
                                "preview_chunk_id": chunk_result.get("chunk_id"),
                                "preview_frame_index": 0,
                                "preview_source_index": 0,
                                "avatar_id": chunk_result.get("avatar_id") or kind,
                            }
                            musetalk_state.set_current_musetalk_frame_data(current_state)
                        current_state["sync_time"] = audio_start_time
                        current_state["audio_started_at"] = audio_start_time
                        musetalk_state.write_musetalk_preview_snapshot(current_state)
                        preview_worker = spawn_route_worker(
                            workers,
                            route_effect_owner,
                            name="nc-delegated-audio-progress",
                            lease=playback_lease,
                            target=lambda token, _owner: stream_delegated_audio_progress(
                                current_state,
                                token,
                            ),
                        )
                        if preview_worker.accepted:
                            preview_stream_handle = preview_worker.value
                        musetalk_state.update_musetalk_pipeline_chunk(
                            current_sequence,
                            reply_id=pipeline_reply_id,
                            playback_state="playing",
                            audio_started_at=audio_start_time,
                        )
                    else:
                        audio_start_time = time.time()
                        run_route_effect(
                            "story_visual_reply",
                            _queue_story_visual_reply,
                            playback_lease,
                            txt,
                            emotion,
                        )
                    if skip_local_playback:
                        run_route_effect(
                            "presence_speaking",
                            _presence_set_state,
                            "speaking",
                        )
                        run_route_effect(
                            "presence_audio_level",
                            _presence_set_audio_level,
                            0.35,
                        )
                        wait_seconds = delegated_playback_duration
                        if wait_seconds <= 0:
                            try:
                                wait_seconds = max(0.0, float(AudioSegment.from_file(path).duration_seconds or 0.0))
                            except Exception:
                                wait_seconds = 0.0
                        if wait_seconds > 0:
                            deadline = time.time() + wait_seconds
                            while (
                                time.time() < deadline
                                and not stop_playback.is_set()
                                and not ctrl.cancel_requested.is_set()
                                and not ctrl.should_skip_message(replay_message_id)
                            ):
                                time.sleep(0.02)
                        else:
                            time.sleep(0.05)
                    else:
                        playback_voice_volume = _tts_playback_voice_volume(source_meta, txt)
                        run_route_effect(
                            "presence_speaking",
                            _presence_set_state,
                            "speaking",
                        )
                        play_audio_file(
                            path,
                            stop_event=_tts_controller_playback_stop_event(
                                ctrl,
                                replay_message_id,
                                service_stop_event,
                            ),
                            volume=playback_voice_volume,
                        )
                    if ctrl.should_skip_message(replay_message_id):
                        print("⏭️ [Replay] Skipped current replay message.")
                    if preview_stream_handle is not None:
                        workers.cancel_handles(
                            (preview_stream_handle,),
                            "playback_preview_complete",
                        )
                        if preview_stream_handle.thread is not threading.current_thread():
                            preview_stream_handle.thread.join(timeout=0.2)
                    audio_elapsed = time.time() - audio_start_time
                    if kind == "musetalk":
                        print(
                            f"⏱️ [MuseTalk] Audio end {chunk_result.get('chunk_id')}: "
                            f"elapsed={audio_elapsed:.2f}s"
                        )
                    ctrl.add_spoken(txt)
                    _record_tts_latency_event(
                        "tts_chunk_playback_end",
                        trace_id=latency_trace_id,
                        duration_ms=round((time.perf_counter() - chunk_playback_started_at) * 1000.0, 3),
                        elapsed_ms=round((time.monotonic() - speak_started_at) * 1000.0, 3),
                        sequence=int(chunk_result.get("sequence_index", chunk_sequence) or chunk_sequence or 0),
                        replay=bool(replay_mode),
                        replay_index=int((source_meta or {}).get("replay_index", 0) or 0),
                        kind=str(kind or ""),
                        skipped=bool(ctrl.should_skip_message(replay_message_id)),
                    )

                if kind == "musetalk" and not stop_flag.is_set():
                    if stop_playback.is_set():
                        run_route_effect(
                            "avatar_idle_transition",
                            transition_musetalk_to_local_idle,
                            advance_to_next_frame=True,
                            work_lease=playback_lease,
                            route_effect_owner=route_effect_owner,
                        )
                    elif ready_for_playback.empty():
                        current_avatar_id = chunk_result.get("avatar_id")
                        admitted, transitioned = run_route_effect(
                            "avatar_default_transition",
                            maybe_transition_musetalk_avatar_back_to_default,
                            current_avatar_id,
                            work_lease=playback_lease,
                            route_effect_owner=route_effect_owner,
                        )
                        if admitted and not transitioned:
                            run_route_effect(
                                "avatar_idle_transition",
                                transition_musetalk_to_local_idle,
                                advance_to_next_frame=True,
                                work_lease=playback_lease,
                                route_effect_owner=route_effect_owner,
                            )
                elif kind in {"none", "scenic"} and not stop_flag.is_set():
                    pass
                else:
                    run_route_effect(
                        "avatar_stream_cleanup",
                        clear_avatar_stream_state,
                        work_lease=playback_lease,
                    )
                safe_delete_with_retry(path)
                if kind in {"musetalk", "none", "scenic"}:
                    admitted, terminal_finished_at = run_route_effect(
                        "terminal_chunk_state",
                        _publish_legacy_terminal_chunk_state,
                        musetalk_state,
                        kind,
                        chunk_result,
                        chunk_sequence,
                        pipeline_reply_id,
                    )
                    if admitted:
                        last_chunk_end_time = terminal_finished_at

                if pause_after_chunk.is_set() and not stop_playback.is_set():
                    pause_after_chunk.clear()
                    _playback_service.pause()
                    end_tts_duck("pause_after_chunk")
                    manual_pause_active.set()
                    playback_paused.set()
                    if avatar_gui:
                        run_route_effect(
                            "avatar_pause",
                            avatar_gui.set_speaking_state,
                            False,
                        )
                    if _is_musetalk_avatar_adapter(avatar_gui):
                        current_avatar_id = chunk_result.get("avatar_id")
                        admitted, transitioned = run_route_effect(
                            "avatar_default_transition",
                            maybe_transition_musetalk_avatar_back_to_default,
                            current_avatar_id,
                            work_lease=playback_lease,
                            route_effect_owner=route_effect_owner,
                        )
                        if admitted and not transitioned:
                            run_route_effect(
                                "avatar_idle_transition",
                                transition_musetalk_to_local_idle,
                                advance_to_next_frame=True,
                                work_lease=playback_lease,
                                route_effect_owner=route_effect_owner,
                            )
                    print("- - - PAUSED (after chunk) - - -")
                    while playback_paused.is_set() and not stop_playback.is_set():
                        time.sleep(0.05)
                    _playback_service.resume()
                    manual_pause_active.clear()
                    if avatar_gui and not stop_playback.is_set():
                        last_resumed_at = time.time()
                        _playback_service.note_resumed(last_resumed_at)
                        run_route_effect(
                            "avatar_resume",
                            avatar_gui.set_speaking_state,
                            True,
                        )
                        last_resume_requested_at = _playback_service.resume_requested_at()
                        if last_resume_requested_at:
                            resume_ms = (last_resumed_at - last_resume_requested_at) * 1000.0
                            message = f"- - - RESUMED - - - ({resume_ms:.1f} ms after request)"
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)
                        else:
                            message = "- - - RESUMED - - -"
                            print(message)
                            musetalk_state.append_musetalk_preview_log(message)

        finally:
            if stop_playback.is_set() and not ctrl.cancel_requested.is_set():
                receipt = _playback_service.skip()
                ctrl.set_playback_receipt(receipt)
            if pipeline_telemetry_enabled:
                run_route_effect(
                    "pipeline_terminal_flags",
                    musetalk_state.update_musetalk_pipeline_flags,
                    reply_id=pipeline_reply_id,
                    active=False,
                    stream_open=False,
                )
            for q in [playback_queue, ready_for_playback]:
                while not q.empty():
                    try:
                        val = q.get_nowait()
                        if val:
                            safe_delete_with_retry(val[0])
                    except:
                        break

            if _is_musetalk_avatar_adapter(avatar_gui) and not stop_flag.is_set():
                if stop_playback.is_set():
                    run_route_effect(
                        "avatar_idle_transition",
                        transition_musetalk_to_local_idle,
                        advance_to_next_frame=True,
                        work_lease=playback_lease,
                        route_effect_owner=route_effect_owner,
                    )
                else:
                    current_avatar_id = getattr(musetalk_state, "current_musetalk_frame_data", {}).get("avatar_id")
                    admitted, transitioned = run_route_effect(
                        "avatar_default_transition",
                        maybe_transition_musetalk_avatar_back_to_default,
                        current_avatar_id,
                        work_lease=playback_lease,
                        route_effect_owner=route_effect_owner,
                    )
                    if admitted and not transitioned:
                        run_route_effect(
                            "avatar_idle_transition",
                            transition_musetalk_to_local_idle,
                            advance_to_next_frame=True,
                            work_lease=playback_lease,
                            route_effect_owner=route_effect_owner,
                        )
            else:
                run_route_effect(
                    "avatar_stream_cleanup",
                    clear_avatar_stream_state,
                    work_lease=playback_lease,
                )
            end_tts_duck("playback_effects_finished")
            run_route_effect("audio_playing_stop", audio_playing.clear)
            run_route_effect(
                "presence_audio_level",
                _presence_set_audio_level,
                0.0,
            )
            run_route_effect(
                "presence_idle",
                _presence_set_state,
                "idle",
            )
            run_route_effect("manual_pause_cleanup", manual_pause_active.clear)
            run_route_effect("pause_after_chunk_cleanup", pause_after_chunk.clear)
            run_route_effect("playback_pause_cleanup", playback_paused.clear)
            run_route_effect(
                "runtime_cleanup",
                schedule_musetalk_runtime_cleanup,
                max_keep=4,
                work_lease=playback_lease,
                route_effect_owner=route_effect_owner,
            )
            if avatar_gui:
                run_route_effect(
                    "avatar_speaking_stop",
                    avatar_gui.set_speaking_state,
                    False,
                )
            if retire_controller_on_completion:
                ctrl.done.set()


class _PlaybackCondition(threading.Condition):
    """Keep existing control notifications and a nonblocking local wake aligned."""
    def __init__(self, local_wakeup):
        super().__init__()
        self._local_wakeup = local_wakeup

    def notify(self, n=1):
        super().notify(n)
        self._local_wakeup.set()


class PlaybackService:
    """Own exactly one device-start admission and one replaceable next route."""

    name = "playback"

    def __init__(
        self,
        *,
        device: PlaybackDevice,
        lease_is_current: LeasePredicate,
        observer: PlaybackObserver | None = None,
        join_timeout_seconds: float = 0.5,
        event_factory: EventFactory = threading.Event,
    ) -> None:
        self._device = device
        self._lease_is_current = lease_is_current
        self._observer = observer
        self._join_timeout_seconds = max(0.0, float(join_timeout_seconds))
        self._event_factory = event_factory
        self._local_wakeup = threading.Event()
        self._condition = _PlaybackCondition(self._local_wakeup)
        self._pause_lock = threading.Lock()
        self._current: PlaybackRoute | None = None
        self._next: PlaybackRoute | None = None
        self._paused = False
        self._stopping = False
        self._stop_callers = 0
        self._next_owner_generation = 1
        self._reserved_owners: dict[int, PlaybackOwner] = {}
        self._current_stop = event_factory()
        self._terminal_owner: PlaybackOwner | None = None
        self._terminal_notification_owner: PlaybackOwner | None = None
        self._terminal_reason = ""
        self._terminal_receipt: PlaybackReceipt | None = None
        self._delivered: list[DeliveredChunk] = []
        self._delivered_keys: set[tuple[int, WorkLease, int]] = set()
        self._pending_start: tuple[PlaybackOwner, int, DeliveredChunk] | None = None
        self._dispatch_reservation: tuple[PlaybackOwner, int, DeliveredChunk] | None = None
        self._shutdown_routes: tuple[PlaybackRoute, ...] = ()
        self._stopped_routes: tuple[PlaybackRoute, ...] = ()
        self._shutdown_reason = ""
        self._worker: threading.Thread | None = None
        self._last_resumed_at = 0.0
        self._resume_requested_at = 0.0
        self._local_session = None
        self._local_route = None
        self._local_finalizing = False
        self._local_notification_thread = None
        self._local_transition = False
        self._local_claiming = False
        self._local_requeue = []
        self._local_retired_sessions = []
        self._local_feeder = None
        self._local_legacy = False
        self._last_local_result = None

    def note_resume_requested(self, value: float) -> None:
        with self._condition:
            self._resume_requested_at = float(value)

    def resume_requested_at(self) -> float:
        with self._condition:
            return self._resume_requested_at

    def note_resumed(self, value: float) -> None:
        with self._condition:
            self._last_resumed_at = float(value)

    def last_resumed_at(self) -> float:
        with self._condition:
            return self._last_resumed_at

    def start(self) -> CommandResult[None]:
        reset_stop_event = self._event_factory()
        with self._condition:
            worker = self._worker
            if worker is not None and worker.is_alive():
                if self._stopping:
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "playback_stop_incomplete",
                            "The previous playback worker is still stopping",
                        ),
                    )
                return CommandResult(True)
            stopped_routes = self._stopped_routes
        if any(self._route_has_live_producers(route) for route in stopped_routes):
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "playback_stop_incomplete",
                    "A previous playback producer is still stopping",
                ),
            )
        with self._condition:
            worker = self._worker
            if worker is not None and worker.is_alive():
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "playback_stop_incomplete",
                        "The previous playback worker is still stopping",
                    ),
                )
            if self._stopped_routes != stopped_routes:
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "playback_stop_incomplete",
                        "Playback lifecycle state changed during restart admission",
                    ),
                )
            self._reset_stopped_state_locked(reset_stop_event)
        self._ensure_worker()
        return CommandResult(True)

    def reserve_owner(self, lease: WorkLease, *, only_if_idle: bool = False) -> CommandResult[PlaybackOwner]:
        if not self._lease_is_current(lease):
            return CommandResult(
                False,
                failure=RuntimeFailure("playback_stale_lease", "Playback lease is stale"),
            )
        with self._condition:
            if only_if_idle and (self._current is not None or self._next is not None or self._reserved_owners):
                return CommandResult(False, failure=RuntimeFailure(
                    "playback_busy", "Existing speech takes priority over this optional announcement."))
            if self._stopping:
                return CommandResult(
                    False,
                    failure=RuntimeFailure("playback_stopped", "Playback is stopping"),
                )
            owner = PlaybackOwner(self._next_owner_generation, lease)
            self._next_owner_generation += 1
            self._reserved_owners[owner.generation] = owner
            return CommandResult(True, owner)

    def release_owner(self, owner: PlaybackOwner) -> bool:
        with self._condition:
            if self._reserved_owners.get(owner.generation) is not owner:
                return False
            self._reserved_owners.pop(owner.generation, None)
            return True

    def enqueue(
        self,
        stream: PreparedStream,
        lease: WorkLease,
        *,
        owner: PlaybackOwner | None = None,
        route_effect_owner: RouteEffectOwner | None = None,
        observer: PlaybackObserver | None = None,
    ) -> CommandResult[str]:
        return self._offer(
            stream,
            lease,
            replace_next=False,
            owner=owner,
            route_effect_owner=route_effect_owner,
            observer=observer,
        )

    def replace_next(
        self,
        stream: PreparedStream,
        lease: WorkLease,
        *,
        owner: PlaybackOwner | None = None,
        route_effect_owner: RouteEffectOwner | None = None,
        observer: PlaybackObserver | None = None,
    ) -> CommandResult[str]:
        return self._offer(
            stream,
            lease,
            replace_next=True,
            owner=owner,
            route_effect_owner=route_effect_owner,
            observer=observer,
        )

    def enqueue_if_idle(self, stream, lease, *, owner=None, route_effect_owner=None, observer=None):
        """Atomically decline optional audio instead of displacing any existing route."""
        return self._offer(stream, lease, replace_next=False, owner=owner,
                           route_effect_owner=route_effect_owner, observer=observer, only_if_idle=True)

    def _offer(
        self,
        stream: PreparedStream,
        lease: WorkLease,
        *,
        replace_next: bool,
        owner: PlaybackOwner | None,
        route_effect_owner: RouteEffectOwner | None,
        observer: PlaybackObserver | None,
        only_if_idle: bool = False,
    ) -> CommandResult[str]:
        if bool(getattr(stream, "cancelled", False)):
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "playback_cancelled_stream",
                    "Cancelled prepared speech cannot enter playback",
                ),
            )
        if not self._lease_is_current(lease):
            return CommandResult(
                False,
                failure=RuntimeFailure("playback_stale_lease", "Playback lease is stale"),
            )
        if owner is not None and owner.lease != lease:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "playback_owner_invalid",
                    "Reserved playback owner does not match the offered lease",
                ),
            )
        if route_effect_owner is not None and (
            owner is None or not route_effect_owner.matches_playback_owner(owner)
        ):
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "route_effect_stale",
                    "Playback offer does not own the exact route-effect generation",
                ),
            )
        displaced = None
        current_stop_event = self._event_factory()
        with self._condition:
            if self._stopping:
                return CommandResult(
                    False,
                    failure=RuntimeFailure("playback_stopped", "Playback is stopping"),
                )
            if only_if_idle and (self._current is not None or self._next is not None):
                return CommandResult(False, failure=RuntimeFailure(
                    "playback_busy", "Existing speech takes priority over this optional announcement."))
            if owner is None:
                owner = PlaybackOwner(self._next_owner_generation, lease)
                self._next_owner_generation += 1
            else:
                reserved = self._reserved_owners.get(owner.generation)
                if reserved is not owner:
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "playback_owner_stale",
                            "Reserved playback owner is no longer admissible",
                        ),
                    )
                if owner.generation != self._next_owner_generation - 1:
                    self._reserved_owners.pop(owner.generation, None)
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "playback_owner_superseded",
                            "A newer playback owner reservation exists",
                        ),
                    )
                self._reserved_owners.pop(owner.generation, None)
            route = PlaybackRoute(stream, lease, owner, route_effect_owner, observer)
            # A cancelled replay can still occupy the serial device while it
            # drains. Its retired generation must not reject fresh normal speech.
            if (self._current is not None
                    and self._terminal_owner != self._current.owner
                    and self._route_is_newer(self._current, route)):
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "playback_route_superseded",
                        "A newer playback route is already active",
                    ),
                )
            if bool(getattr(stream, "cancelled", False)):
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "playback_cancelled_stream",
                        "Cancelled prepared speech cannot enter playback",
                    ),
                )
            if self._current is None:
                self._current = route
                self._current_stop = current_stop_event
                self._terminal_owner = None
                self._terminal_reason = ""
                self._terminal_receipt = None
                position = "current"
            else:
                existing = self._next
                if existing is not None and self._route_is_newer(existing, route):
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "playback_route_superseded",
                            "A newer playback route is already queued",
                        ),
                    )
                if existing is not None and not replace_next:
                    displaced = existing
                elif existing is not None:
                    displaced = existing
                self._next = route
                position = "next"
            self._condition.notify_all()
        self._cancel_route(displaced, "playback_superseded")
        self._ensure_worker()
        return CommandResult(True, position)

    def interrupt(self, reason: str) -> PlaybackReceipt:
        return self._terminate(str(reason or "interrupted"), stop_service=False)

    def cancel_stream(
        self,
        stream: PreparedStream,
        reason: str = "playback_cancelled",
    ) -> CommandResult[PlaybackReceipt]:
        """Cancel only the route backed by ``stream`` without touching another owner."""

        resolved_reason = str(reason or "playback_cancelled")
        while True:
            with self._condition:
                local_route = self._current if self._current is not None and self._current.stream is stream else None
            local_receipt = self._finalize_local(local_route, resolved_reason)
            if local_receipt is not None:
                self._cancel_route(local_route, resolved_reason)
                return CommandResult(True, local_receipt)
            stop_event = None
            route = None
            receipt = None
            notify_finished = False
            with self._condition:
                if self._current is not None and self._current.stream is stream:
                    route = self._current
                    if self._local_route is route:
                        continue  # Reconcile the newly published local session outside the condition.
                    if self._terminal_owner == route.owner and self._terminal_receipt is not None:
                        receipt = self._terminal_receipt
                    else:
                        self._terminal_owner = route.owner
                        self._terminal_notification_owner = route.owner
                        self._terminal_reason = resolved_reason
                        self._paused = False
                        self._pending_start = None
                        self._dispatch_reservation = None
                        stop_event = self._current_stop
                        receipt = PlaybackReceipt(
                            tuple(self._delivered),
                            resolved_reason,
                            route.owner,
                        )
                        self._terminal_receipt = receipt
                        notify_finished = True
                        self._condition.notify_all()
                elif self._next is not None and self._next.stream is stream:
                    route = self._next
                    self._next = None
                    receipt = PlaybackReceipt((), resolved_reason, route.owner)
                    self._condition.notify_all()
                else:
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "playback_route_not_found",
                            "The exact playback stream is not active or queued",
                        ),
                    )
            break
        if stop_event is not None:
            stop_event.set()
        if notify_finished:
            try:
                self._notify_finished(
                    receipt,
                    route.effect_owner if route is not None else None,
                    route.observer if route is not None else None,
                )
            finally:
                with self._condition:
                    if self._terminal_notification_owner == route.owner:
                        self._terminal_notification_owner = None
                    self._condition.notify_all()
        self._cancel_route(route, resolved_reason)
        return CommandResult(True, receipt)

    def cancel_lease(
        self,
        lease: WorkLease,
        reason: str = "playback_cancelled",
    ) -> CommandResult[PlaybackReceipt | None]:
        with self._condition:
            route = next(
                (
                    candidate
                    for candidate in (self._current, self._next)
                    if candidate is not None and candidate.lease == lease
                ),
                None,
            )
        if route is None:
            return CommandResult(True, None)
        cancelled = self.cancel_stream(route.stream, reason)
        return CommandResult(
            cancelled.accepted,
            cancelled.value,
            cancelled.failure,
        )

    def skip_stream_chunk(self, stream: PreparedStream) -> CommandResult[None]:
        """Stop only the current chunk while preserving the exact stream route."""

        local_result = self._skip_local_chunk(stream)
        if local_result is not None:
            return local_result
        replacement_stop = self._event_factory()
        with self._condition:
            route = self._current
            if (
                route is None
                or route.stream is not stream
                or self._terminal_owner == route.owner
                or self._stopping
            ):
                return CommandResult(
                    False,
                    failure=RuntimeFailure(
                        "playback_route_not_found",
                        "The exact playback stream is not current",
                    ),
                )
            stop_event = self._current_stop
            self._current_stop = replacement_stop
            self._pending_start = None
            self._dispatch_reservation = None
            self._condition.notify_all()
        stop_event.set()
        try:
            self._device.stop(route.owner)
        except BaseException:
            pass
        return CommandResult(True)

    def skip(self) -> PlaybackReceipt:
        return self._terminate("skip", stop_service=False, cancel_current=True)

    def stop(self, reason: str = "runtime_shutdown") -> PlaybackReceipt:
        with self._condition:
            self._stop_callers += 1
        try:
            return self._stop_service(reason)
        finally:
            with self._condition:
                self._stop_callers -= 1
                self._condition.notify_all()

    def _stop_service(self, reason: str) -> PlaybackReceipt:
        receipt = self._terminate(str(reason or "runtime_shutdown"), stop_service=True)
        self._ensure_shutdown_worker()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(self._join_timeout_seconds)
        if worker is not None and worker.is_alive():
            failure = RuntimeFailure(
                "playback_stop_timeout",
                f"Playback worker did not stop within {self._join_timeout_seconds:.3f}s",
            )
            return replace(receipt, failure=failure)
        with self._condition:
            if self._terminal_receipt is not None and (
                receipt.owner is None or self._terminal_receipt.owner == receipt.owner
            ):
                receipt = self._terminal_receipt
            stopped_routes = self._stopped_routes
        route_failure = None
        for route in stopped_routes:
            failure = getattr(route.stream, "failure", None)
            if self._route_has_live_producers(route):
                route_failure = failure or RuntimeFailure(
                    "playback_producer_stop_timeout",
                    "A previous playback producer is still stopping",
                )
                break
            if failure is None or getattr(
                failure, "category", ""
            ) == "playback_producer_stop_timeout":
                continue
            route_failure = failure
            break
        if route_failure is None and receipt.failure is not None:
            category = getattr(receipt.failure, "category", "")
            if category not in {
                "playback_preflight_error",
                "playback_producer_stop_timeout",
                "playback_stop_timeout",
                "speech_cancelled",
            }:
                route_failure = receipt.failure
        return replace(receipt, failure=route_failure)

    def pause(self) -> CommandResult[None]:
        return self._set_paused(True)

    def pause_stream(self, stream: PreparedStream) -> CommandResult[None]:
        return self._set_paused(True, stream=stream)

    def resume_stream(self, stream: PreparedStream) -> CommandResult[None]:
        return self._set_paused(False, stream=stream)

    def _set_paused(
        self,
        paused: bool,
        *,
        stream: PreparedStream | None = None,
    ) -> CommandResult[None]:
        with self._pause_lock:
            return self._apply_paused(paused, stream=stream)

    def _apply_paused(self, paused: bool, *, stream=None) -> CommandResult[None]:
        with self._condition:
            while self._local_transition:
                self._condition.wait()
            if (
                self._stopping
                or self._current is None
                or (stream is not None and self._current.stream is not stream)
            ):
                return CommandResult(False, failure=RuntimeFailure("playback_idle", "No playback is active"))
            session = self._local_session if self._local_route is self._current else None
            self._paused = bool(paused)
        if session is not None:
            session.set_paused(paused)
        with self._condition:
            self._condition.notify_all()
        return CommandResult(True)

    def resume(self) -> CommandResult[None]:
        return self._set_paused(False)

    def snapshot(self) -> PlaybackSnapshot:
        with self._condition:
            return PlaybackSnapshot(
                current=self._current,
                next=self._next,
                paused=self._paused,
                terminal=self._terminal_owner is not None,
                stopping=self._stopping,
            )

    def activity_snapshot(self) -> PlaybackSnapshot:
        """Live activity for indexing; keep the separate admission stop latch intact."""
        with self._condition:
            snapshot = self.snapshot()
            if self._stop_callers:
                return replace(snapshot, stopping=True)
            if not snapshot.stopping:
                return snapshot
            stopped_routes = self._stopped_routes
            pending = bool(
                self._shutdown_routes
                or (self._worker is not None and self._worker.is_alive())
                or self._local_session is not None
                or self._local_route is not None
                or self._local_feeder is not None
                or self._local_retired_sessions
                or self._local_finalizing or self._local_transition or self._local_claiming
                or self._terminal_notification_owner is not None
                or self._local_notification_thread is not None
            )
        # Producer callbacks can acquire their own locks; never call them under
        # the playback condition. Unknown producer state stays busy.
        if pending or any(self._route_has_live_producers(route) for route in stopped_routes):
            return snapshot
        with self._condition:
            if self._stop_callers:
                return replace(self.snapshot(), stopping=True)
            if not self._stopping or self._stopped_routes is not stopped_routes:
                return self.snapshot()
            return replace(snapshot, stopping=False)

    def lease_is_current(self, lease: WorkLease) -> bool:
        return bool(self._lease_is_current(lease))

    def finish_current(self) -> None:
        while True:
            with self._condition:
                local_route = self._current
            if self._finalize_local(local_route, "completed") is not None:
                return
            stop_event = None
            receipt = None
            with self._condition:
                route = self._current
                if route is None:
                    return
                if self._local_route is route:
                    continue  # Local publication won the serial-selection race.
                self._terminal_owner = route.owner
                self._terminal_reason = "completed"
                self._pending_start = None
                self._dispatch_reservation = None
                stop_event = self._current_stop
                receipt = PlaybackReceipt(tuple(self._delivered), "completed", route.owner)
                self._terminal_receipt = receipt
                self._condition.notify_all()
            break
        stop_event.set()
        self._notify_finished(receipt, route.effect_owner, route.observer)
        with self._condition:
            deadline = time.monotonic() + self._join_timeout_seconds
            while self._current is route and time.monotonic() < deadline:
                self._condition.wait(max(0.0, deadline - time.monotonic()))

    def mark_started(self, chunk: object, owner: PlaybackOwner | None = None) -> bool:
        try:
            index = int(getattr(chunk, "index", chunk))
            text = str(getattr(chunk, "text", ""))
            skip_local = bool(dict(getattr(chunk, "source_metadata", {}) or {}).get("skip_local_playback", False))
        except (TypeError, ValueError):
            return False
        with self._condition:
            route = self._current
            expected = owner or (route.owner if route is not None else None)
            if (
                route is None
                or expected != route.owner
                or self._terminal_owner == route.owner
                or self._stopping
            ):
                return False
            delivered = DeliveredChunk(
                index=index,
                text=text,
                lease=route.lease,
                owner_generation=route.owner.generation,
                audio_start_pending=bool(
                    getattr(self._device, "supports_audio_start", False)
                    and not callable(getattr(route.stream, "playback_callback", None))
                    and not skip_local
                ),
            )
            self._pending_start = (route.owner, index, delivered)
            return True

    def commit_started(self, chunk: object, owner: PlaybackOwner) -> bool:
        try:
            index = int(getattr(chunk, "index", chunk))
        except (TypeError, ValueError):
            return False
        chunk_lease = getattr(chunk, "lease", None)
        if chunk_lease is not None and not self._lease_is_current(chunk_lease):
            return False
        with self._condition:
            route = self._current
            pending = self._pending_start
            if (
                route is None
                or route.owner != owner
                or self._terminal_owner == owner
                or self._stopping
                or pending is None
                or pending[0] != owner
                or pending[1] != index
                or (chunk_lease is not None and chunk_lease != route.lease)
            ):
                return False
            self._pending_start = None
            self._dispatch_reservation = pending
            return True

    def admit_dispatch(
        self,
        chunk: object,
        owner: PlaybackOwner,
        stop_event: object | None = None,
    ) -> bool:
        try:
            index = int(getattr(chunk, "index", chunk))
        except (TypeError, ValueError):
            return False
        chunk_lease = getattr(chunk, "lease", None)
        candidate_lease = chunk_lease or owner.lease
        if not self._lease_is_current(candidate_lease):
            return False
        if stop_event is not None and bool(stop_event.is_set()):
            return False
        notify_chunk = None
        with self._condition:
            route = self._current
            reservation = self._dispatch_reservation
            if (
                route is None
                or route.owner != owner
                or route.lease != candidate_lease
                or self._terminal_owner == owner
                or self._stopping
                or reservation is None
                or reservation[0] != owner
                or reservation[1] != index
                or (stop_event is not None and self._current_stop is not stop_event)
            ):
                return False
            self._dispatch_reservation = None
            delivered = reservation[2]
            key = (route.owner.generation, route.lease, index)
            if key not in self._delivered_keys:
                self._delivered_keys.add(key)
                self._delivered.append(delivered)
                notify_chunk = delivered
        if notify_chunk is not None:
            self._notify_started(notify_chunk, route.effect_owner, route.observer)
        return True

    def _terminate(
        self,
        reason: str,
        *,
        stop_service: bool,
        cancel_current: bool = False,
    ) -> PlaybackReceipt:
        while True:
            with self._condition:
                local_route = self._current
            local_receipt = self._finalize_local(local_route, reason, stop_service=stop_service)
            if local_receipt is not None:
                if cancel_current:
                    self._cancel_route(local_route, reason)
                return local_receipt
            receipt = self._terminate_serial(reason, stop_service=stop_service, cancel_current=cancel_current)
            if receipt is not None:
                return receipt

    def _terminate_serial(self, reason, *, stop_service, cancel_current):
        """Legacy terminal path; retry if local ownership appeared meanwhile."""
        stop_event = None
        cancellation_route = None
        notify_finished = False
        with self._condition:
            current = self._current
            if current is not None and self._local_route is current:
                return None
            if stop_service:
                if self._stopping:
                    return self._terminal_receipt or PlaybackReceipt(
                        tuple(self._delivered), reason
                    )
                detached = tuple(
                    route for route in (self._current, self._next) if route is not None
                )
                self._current = None
                self._next = None
                self._paused = False
                self._stopping = True
                self._pending_start = None
                self._dispatch_reservation = None
                self._shutdown_routes = detached
                self._stopped_routes = detached
                self._shutdown_reason = reason
                if current is not None:
                    self._terminal_owner = current.owner
                    self._terminal_reason = reason
                    stop_event = self._current_stop
                    receipt = self._terminal_receipt or PlaybackReceipt(
                        tuple(self._delivered), reason, current.owner
                    )
                else:
                    receipt = self._terminal_receipt or PlaybackReceipt(
                        tuple(self._delivered), reason
                    )
                self._terminal_receipt = receipt
                notify_finished = current is not None
                self._condition.notify_all()
            elif current is None:
                return self._terminal_receipt or PlaybackReceipt(tuple(self._delivered), reason)
            elif self._terminal_owner == current.owner and self._terminal_receipt is not None:
                receipt = self._terminal_receipt
                if cancel_current:
                    cancellation_route = current
                else:
                    return receipt
            else:
                self._terminal_owner = current.owner
                self._terminal_reason = reason
                self._paused = False
                self._pending_start = None
                self._dispatch_reservation = None
                stop_event = self._current_stop
                receipt = PlaybackReceipt(tuple(self._delivered), reason, current.owner)
                self._terminal_receipt = receipt
                notify_finished = True
                if cancel_current:
                    cancellation_route = current
                self._condition.notify_all()
        if stop_event is not None:
            stop_event.set()
        if cancellation_route is not None:
            self._cancel_route(cancellation_route, reason)
            failure = getattr(cancellation_route.stream, "failure", None)
            if failure is not None:
                receipt = replace(receipt, failure=failure)
                with self._condition:
                    if self._terminal_receipt is not None and self._terminal_receipt.owner == receipt.owner:
                        self._terminal_receipt = receipt
            deadline = time.monotonic() + self._join_timeout_seconds
            with self._condition:
                while self._current is cancellation_route:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure = RuntimeFailure(
                            "playback_skip_timeout",
                            "Playback route did not finish cleanup before skip returned",
                        )
                        receipt = replace(receipt, failure=failure)
                        if (
                            self._terminal_receipt is not None
                            and self._terminal_receipt.owner == receipt.owner
                        ):
                            self._terminal_receipt = receipt
                        break
                    self._condition.wait(remaining)
                if self._current is None:
                    self._terminal_receipt = receipt
        if notify_finished:
            self._notify_finished(
                receipt,
                current.effect_owner if current is not None else None,
                current.observer if current is not None else None,
            )
        return receipt

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while not self._stopping and (self._current is None or (self._paused and self._local_session is None)):
                        self._condition.wait(0.05)
                    if self._stopping:
                        shutdown_routes = self._shutdown_routes
                        self._shutdown_routes = ()
                        shutdown_reason = self._shutdown_reason or "runtime_shutdown"
                    else:
                        shutdown_routes = ()
                        shutdown_reason = ""
                    route = self._current
                    stopping = self._stopping
                    terminal = route is not None and self._terminal_owner == route.owner
                    stop_event = self._current_stop
                if stopping:
                    self._cleanup_shutdown(shutdown_routes, shutdown_reason)
                    return
                if route is None:
                    continue
                if terminal:
                    self._cleanup_and_promote(route, self._terminal_reason or "runtime_shutdown")
                    continue

                if self._run_local(route, stop_event):
                    continue

                handoff = self._next_prepared(route)
                if handoff is None:
                    state, reason = self._stream_terminal_state(route.stream)
                    if state == "active":
                        self._notify_waiting(route)
                        continue
                    if state == "failed":
                        self._set_terminal(route, reason)
                        continue
                    self._complete_and_promote(route, reason)
                    continue

                prepared = getattr(handoff, "chunk", handoff)
                if not self.mark_started(prepared, route.owner):
                    self._discard_prepared(route.stream, prepared)
                    continue
                if not self.commit_started(prepared, route.owner):
                    self._discard_prepared(route.stream, prepared)
                    continue
                try:
                    callback = getattr(route.stream, "playback_callback", None)
                    if callable(callback):
                        if bool(
                            getattr(
                                route.stream,
                                "playback_callback_consumes_stream",
                                False,
                            )
                        ):
                            if not self.admit_dispatch(prepared, route.owner, stop_event):
                                self._discard_prepared(route.stream, prepared)
                                continue
                            callback_args = (
                                self._callback_chunks(route, prepared),
                                stop_event,
                                route.owner,
                            )
                            if route.effect_owner is not None and bool(
                                getattr(
                                    callback,
                                    "accepts_route_effect_owner",
                                    False,
                                )
                            ):
                                callback(*callback_args, route.effect_owner)
                            elif route.effect_owner is not None:
                                callback_result = route.effect_owner.run_step(
                                    "playback_callback",
                                    lambda: callback(*callback_args),
                                )
                                if not callback_result.accepted:
                                    raise RuntimeError(
                                        callback_result.failure.message
                                        if callback_result.failure is not None
                                        else "Playback callback lost route authority."
                                    )
                            else:
                                callback(*callback_args)
                        else:
                            if not self.admit_dispatch(prepared, route.owner, stop_event):
                                self._discard_prepared(route.stream, prepared)
                                continue
                            if route.effect_owner is not None and bool(
                                getattr(
                                    callback,
                                    "accepts_route_effect_owner",
                                    False,
                                )
                            ):
                                callback(
                                    prepared,
                                    stop_event,
                                    route.owner,
                                    route.effect_owner,
                                )
                            elif route.effect_owner is not None:
                                callback_result = route.effect_owner.run_step(
                                    "playback_callback",
                                    lambda: callback(
                                        prepared,
                                        stop_event,
                                        route.owner,
                                    ),
                                )
                                if not callback_result.accepted:
                                    raise RuntimeError(
                                        callback_result.failure.message
                                        if callback_result.failure is not None
                                        else "Playback callback lost route authority."
                                    )
                            else:
                                callback(prepared, stop_event, route.owner)
                        mark_done = getattr(route.stream, "mark_done", None)
                        if callable(mark_done):
                            mark_done()
                    else:
                        if not self.admit_dispatch(prepared, route.owner, stop_event):
                            self._discard_prepared(route.stream, prepared)
                            continue
                        if bool(getattr(self._device, "supports_audio_start", False)):
                            self._device.play(
                                prepared, stop_event, route.owner,
                                on_started=lambda _route=route, _chunk=prepared, _stop=stop_event:
                                    self._notify_audio_started(_route, _chunk, _stop),
                            )
                        else:
                            self._device.play(prepared, stop_event, route.owner)
                    self._notify_paused(route)
                except BaseException:
                    self._set_terminal(route, "playback_error")
        finally:
            with self._condition:
                if self._worker is threading.current_thread():
                    self._worker = None
                self._condition.notify_all()

    def _wake_local(self):
        self._local_wakeup.set()

    def _run_local(self, route, stop_event):
        """Optional queued path; custom callbacks and serial devices stay unchanged."""
        factory = getattr(self._device, "open_local_session", None)
        if (not callable(factory) or callable(getattr(route.stream, "playback_callback", None))
                or not bool(getattr(route.stream, "local_playback_eligible", True))
                or not callable(getattr(route.stream, "next_local_ready", None))
                or not callable(getattr(route.stream, "preflight_local_audio", None))
                or not callable(getattr(route.stream, "start_local_feeder", None))):
            return False
        with self._condition:
            session = self._local_session if self._local_route is route else None
        if session is None:
            try:
                session = factory(route.owner, stop_event)
            except BaseException:
                return False  # No source ownership or device submission yet.
            if session is None:
                return False
            if session.owner is not route.owner or session.stop_event is not stop_event:
                session.close()
                self._set_terminal(route, "playback_owner_invalid")
                return True
            session.set_wakeup(self._wake_local)
            with self._pause_lock:
                with self._condition:
                    admitted = (self._current is route and self._current_stop is stop_event
                                and self._terminal_owner != route.owner and not self._stopping)
                    if admitted:
                        self._local_session, self._local_route = session, route
                        paused = self._paused
                if admitted:
                    session.set_paused(paused)
            if not admitted:
                session.close()
                return True
        if self._local_feeder is None:
            from core.runtime.local_playback import LocalPlaybackFeeder
            feeder = LocalPlaybackFeeder()
            with self._condition:
                self._local_feeder = feeder
            spawned = route.stream.start_local_feeder(
                lambda token, _owner: self._feed_local(route, feeder, token))
            if not spawned.accepted or spawned.value is None:
                self._finalize_local(route, "playback_feeder_start_error")
                return True
            feeder.worker = spawned.value
        feeder = self._local_feeder
        pending = None
        progress_at = 0.0
        progress_state = None
        try:
            while True:
                with self._condition:
                    while self._local_transition:
                        self._condition.wait()
                    active = (self._current is route and self._current_stop is stop_event
                              and self._local_session is session
                              and self._terminal_owner != route.owner and not self._stopping)
                if not active:
                    return True
                if not self._lease_is_current(route.lease):
                    self._finalize_local(route, "playback_stale_lease", local_epoch=(session, stop_event))
                    return True
                events = session.poll()
                with self._condition:
                    if (self._local_transition or self._current is not route
                            or self._current_stop is not stop_event or self._local_session is not session
                            or self._terminal_owner == route.owner or self._stopping):
                        continue
                for event in events:
                    if event.kind == "started":
                        self._record_local_start(route, event, stop_event)
                    elif event.kind == "ended":
                        session.notify_ended(event.prepared.index)
                    elif event.kind == "paused":
                        self._notify_local_progress(route, session, stop_event)
                        session.notify_state("paused")
                        self._notify_paused(route)
                    elif event.kind == "waiting":
                        self._notify_local_progress(route, session, stop_event)
                        session.notify_state("waiting")
                        self._notify_waiting(route)
                now = time.monotonic()
                sample = session.chunk_clock_sample()
                clock_state = (sample.key, sample.running) if sample is not None else None
                if events or now >= progress_at or clock_state != progress_state:
                    self._notify_local_progress(route, session, stop_event)
                    progress_at = now + 1.0 / 30.0
                    progress_state = clock_state
                session.notify_progress()
                if session.failure is not None:
                    if session.submitted_any or self._local_legacy or session._output.error is None:
                        self._finalize_local(route, session.failure.category, local_epoch=(session, stop_event))
                        return True
                    # A failed open before any submission can hand its files
                    # back once. Later failures never replay scheduled speech.
                    session.revoke("legacy_fallback")
                    retained = list(session.release_unstarted())
                    session._trace("local_playback_fallback", {"reason": session.failure.category})
                    try:
                        session = self._replace_local_portion(route, session, stop_event)
                        self._local_legacy = True
                        pending = None
                        while retained:
                            chunk, audio = retained.pop(0)
                            self._play_local_serial(route, chunk, audio, stop_event)
                    finally:
                        for chunk, _audio in retained:
                            source = getattr(chunk, "audio_source", None)
                            if source is not None:
                                feeder.cleanup.put(source.close)
                            feeder.cleanup.put(str(getattr(chunk, "audio_path", "") or ""))
                    continue
                if pending is not None:
                    if session.enqueue(*pending):
                        pending = None
                        continue
                else:
                    with self._condition:
                        if (self._local_transition or self._current is not route
                                or self._current_stop is not stop_event or self._local_session is not session
                                or self._terminal_owner == route.owner or self._stopping):
                            continue
                        retained = self._local_requeue.pop(0) if self._local_requeue else None
                    if retained is not None:
                        pending = retained
                        continue
                with self._condition:
                    delegated = (feeder.ready and bool(dict(getattr(feeder.prepared,
                        "source_metadata", {}) or {}).get("skip_local_playback", False)))
                    serial_ready = pending is None and feeder.ready and (delegated or self._local_legacy)
                if serial_ready:
                    session.finish_input()
                    if not session.drained:
                        with self._condition:
                            self._condition.wait(.005)
                        continue
                    with self._condition:
                        if self._paused:
                            self._condition.wait(.005)
                            continue
                        if self._local_transition or self._current_stop is not stop_event:
                            continue
                    session = self._replace_local_portion(route, session, stop_event)
                    with self._condition:
                        if self._terminal_owner == route.owner or self._stopping:
                            continue
                        chunk, audio = feeder.prepared, feeder.audio
                        feeder.prepared = feeder.audio = None
                        feeder.ready = False
                    self._play_local_serial(route, chunk, audio, stop_event)
                    continue
                with self._condition:
                    if (pending is None and feeder.ready and not self._local_transition
                            and self._current is route and self._local_session is session
                            and self._current_stop is stop_event and self._terminal_owner != route.owner
                            and not self._stopping):
                        session.adopt(feeder.prepared, feeder.audio)
                        pending = (feeder.prepared, feeder.audio)
                        feeder.prepared = feeder.audio = None
                        feeder.ready = False
                        self._condition.notify_all()
                    producer_done = feeder.done and feeder.prepared is None
                    feeder_failure = feeder.failure
                if feeder_failure is not None:
                    self._finalize_local(route, feeder_failure.category, local_epoch=(session, stop_event))
                    return True
                if pending is not None:
                    continue
                if producer_done:
                    session.finish_input()
                if session.drained:
                    state, terminal_reason = self._stream_terminal_state(route.stream)
                    if state == "active":
                        terminal_reason = "completed"
                    self._complete_and_promote(route, terminal_reason, local_epoch=(session, stop_event))
                    return True
                with self._condition:
                    self._local_wakeup.clear()
                    # Test producer/control predicates under the same condition
                    # used by their notifications. Source dirty state persists
                    # across an earlier notification until the next poll.
                    if (feeder.ready or feeder.failure is not None or self._local_requeue
                            or (feeder.done and feeder.prepared is None) != producer_done
                            or self._local_transition or self._current is not route
                            or self._current_stop is not stop_event or self._stopping
                            or self._terminal_owner == route.owner):
                        continue
                    wait_seconds = session.next_wakeup_seconds
                self._local_wakeup.wait(wait_seconds)
        except BaseException:
            self._finalize_local(route, "playback_error", local_epoch=(session, stop_event))
            return True

    def _replace_local_portion(self, route, session, stop_event):
        with self._condition:
            while self._local_transition:
                self._condition.wait()
            if (self._current is not route or self._current_stop is not stop_event
                    or self._local_session is not session
                    or self._terminal_owner == route.owner or self._stopping):
                raise RuntimeError("Local portion no longer owns the route")
            self._local_transition = True
            while self._local_claiming:
                self._condition.wait()
        replacement = None
        try:
            replacement = self._device.open_local_session(route.owner, stop_event)
            if replacement is None or replacement.owner is not route.owner or replacement.stop_event is not stop_event:
                raise RuntimeError("Local portion replacement lost route ownership")
            replacement.set_wakeup(self._wake_local)
            replacement.share_cleanup(session)
            session.retire()
            with self._condition:
                paused = self._paused
            replacement.set_paused(paused)
            with self._condition:
                self._local_session = replacement
        except BaseException:
            if replacement is not None:
                replacement.retire()
            raise
        finally:
            with self._condition:
                self._local_transition = False
                self._condition.notify_all()
        session.flush_retired_effects()
        return replacement

    def _play_local_serial(self, route, prepared, audio, stop_event):
        # File ownership transfers to the established serial device, whose
        # finally block performs deletion. Do not decode an already-prepared file.
        with self._condition:
            while (self._paused and self._current is route
                    and self._terminal_owner != route.owner and not self._stopping):
                self._condition.wait(.005)
        if not (self.mark_started(prepared, route.owner)
                and self.commit_started(prepared, route.owner)
                and self.admit_dispatch(prepared, route.owner, stop_event)):
            source = getattr(prepared, "audio_source", None)
            if source is not None:
                self._local_session._cleanup_lane.put(source.close)
            self._local_session._cleanup_lane.put(str(getattr(prepared, "audio_path", "") or ""))
            return
        chunk = replace(prepared, playback_audio=audio) if audio is not None else prepared
        if bool(getattr(self._device, "supports_audio_start", False)):
            self._device.play(chunk, stop_event, route.owner,
                on_started=lambda: self._notify_audio_started(route, prepared, stop_event))
        else:
            self._device.play(chunk, stop_event, route.owner)

    def _feed_local(self, route, feeder, token):
        """Ordered file ownership and slow preparation, never the control lane."""
        try:
            with self._condition:
                if feeder.cancelled or self._terminal_owner == route.owner or self._stopping:
                    return
                feeder.cleanup = self._local_session._cleanup_lane
                feeder.cleanup.retain()
            while True:
                with self._condition:
                    candidate_session = self._local_session
                capacity = candidate_session is not None and candidate_session.can_prepare
                with self._condition:
                    if (feeder.cancelled or token.is_set() or self._current is not route
                            or self._terminal_owner == route.owner or self._stopping):
                        return
                    session = self._local_session
                    if (self._local_transition or feeder.prepared is not None
                            or session is not candidate_session or not capacity):
                        self._condition.wait(.005)
                        continue
                    self._local_claiming = True
                try:
                    handoff = self._next_prepared(route, local=True)
                    if handoff is not None:
                        with self._condition:
                            feeder.prepared = getattr(handoff, "chunk", handoff)
                finally:
                    with self._condition:
                        self._local_claiming = False
                        self._condition.notify_all()
                if handoff is None:
                    state, reason = self._stream_terminal_state(route.stream)
                    if state != "active":
                        with self._condition:
                            feeder.done = True
                            if state == "failed":
                                feeder.failure = RuntimeFailure(reason, "Local source ended unsuccessfully")
                            self._condition.notify_all()
                        return
                    continue
                prepared = feeder.prepared
                if bool(dict(getattr(prepared, "source_metadata", {}) or {}).get("skip_local_playback", False)):
                    with self._condition:
                        feeder.ready = True
                        self._condition.notify_all()
                    continue
                size = session.estimated_audio_bytes(prepared)
                while True:
                    with self._condition:
                        candidate_session = self._local_session
                    budget = candidate_session is not None and candidate_session.can_prepare_bytes(size)
                    with self._condition:
                        if (feeder.cancelled or token.is_set() or self._current is not route
                                or self._terminal_owner == route.owner or self._stopping):
                            return
                        session = self._local_session
                        if not self._local_transition and session is candidate_session and budget:
                            break
                        self._condition.wait(.005)
                audio = session.prepare_detached(prepared)
                preflight = route.stream.preflight_local_audio(prepared)
                if not preflight.accepted or not preflight.value:
                    raise RuntimeError("Local audio preflight declined")
                with self._condition:
                    if (feeder.cancelled or token.is_set() or self._current is not route
                            or self._terminal_owner == route.owner or self._stopping
                            or not self._lease_is_current(route.lease)):
                        return
                    feeder.audio, feeder.ready = audio, True
                    self._condition.notify_all()
        except BaseException as exc:
            with self._condition:
                feeder.failure = RuntimeFailure("playback_preflight_error", str(exc), exc)
                self._condition.notify_all()
        finally:
            with self._condition:
                discarded = feeder.prepared
                feeder.prepared = feeder.audio = None
                feeder.ready = False
                feeder.done = True
                self._condition.notify_all()
            if discarded is not None:
                source = getattr(discarded, "audio_source", None)
                if source is not None:
                    feeder.cleanup.put(source.close)
                feeder.cleanup.put(str(getattr(discarded, "audio_path", "") or ""))
            if feeder.cleanup is not None:
                feeder.cleanup.release()

    def _record_local_start(self, route, event, stop_event, *, terminal_reconcile=False):
        prepared = event.prepared
        if event.kind != "started" or prepared is None or getattr(prepared, "lease", None) is not route.lease:
            return
        with self._condition:
            if (self._local_route is not route or self._current is not route
                    or self._current_stop is not stop_event):
                return
            if not terminal_reconcile and (self._terminal_owner == route.owner or self._stopping):
                return
            key = (route.owner.generation, route.lease, prepared.index)
            duplicate = key in self._delivered_keys
            delivered = DeliveredChunk(prepared.index, prepared.text, route.lease,
                route.owner.generation, False, event.monotonic_time)
            if not duplicate:
                self._delivered_keys.add(key)
                self._delivered.append(delivered)
            session = self._local_session
        session.acknowledge_start(prepared)
        if not duplicate and not terminal_reconcile and not stop_event.is_set() and self._lease_is_current(route.lease):
            delivered = replace(delivered, audio_clock_sample=session.chunk_clock_sample(prepared.index))
            self._notify_started(delivered, route.effect_owner, route.observer)
            self._notify_audio_started(route, prepared, stop_event)
            session.notify_started(prepared)

    def _notify_local_progress(self, route, session, stop_event, *, terminal=False):
        """Sample on the owned control lane; never invoke observers under the service lock."""
        callback = getattr(route.observer or self._observer, "on_audio_progress", None)
        if not callable(callback) or (not terminal and stop_event.is_set()) or not self._lease_is_current(route.lease):
            return
        sample = session.chunk_clock_sample()
        if sample is None:
            return
        with self._condition:
            terminal_route = (terminal and self._current is None and self._terminal_receipt is not None
                              and self._terminal_receipt.owner == route.owner)
            if ((self._current is not route and not terminal_route) or self._local_session is not session
                    or self._current_stop is not stop_event
                    or (not terminal and (self._terminal_owner == route.owner or self._stopping))):
                return
            delivered = next((chunk for chunk in reversed(self._delivered)
                if chunk.index == sample.key and chunk.lease == route.lease
                and chunk.owner_generation == route.owner.generation), None)
        if delivered is None:
            return
        try:
            if route.effect_owner is None:
                callback(delivered, sample)
            else:
                route.effect_owner.run_step("playback_observer_audio_progress",
                                           lambda: callback(delivered, sample))
        except BaseException:
            pass

    def _finalize_local(self, route, reason, *, stop_service=False, local_epoch=None):
        """Freeze, revoke outside the condition, then publish one reconciled receipt."""
        with self._condition:
            while self._local_transition or self._local_finalizing:
                self._condition.wait()
            if local_epoch is not None and (self._current is not route
                    or self._local_session is not local_epoch[0]
                    or self._current_stop is not local_epoch[1]):
                return None
            if stop_service:
                if self._stopping:
                    return self._terminal_receipt
                # Stop owns the service, not the earlier capture: a route may
                # have completed/promoted while this caller was outside locks.
                route = self._current
            if self._last_local_result is not None and self._last_local_result[0] is route:
                if stop_service:
                    self._stop_local_locked(reason)
                return self._last_local_result[1]
            if route is None or self._local_route is not route:
                return None
            if self._terminal_receipt is not None and self._terminal_receipt.owner is route.owner:
                if stop_service:
                    self._stop_local_locked(reason)
                return self._terminal_receipt
            if self._current is not route:
                return None
            session, stop_event = self._local_session, self._current_stop
            self._local_finalizing = True
            self._terminal_owner = route.owner
            self._terminal_reason = reason
            self._terminal_notification_owner = route.owner
            self._paused = False
            self._condition.notify_all()
            if stop_service:
                self._stop_local_locked(reason, detach=False)
        stop_event.set()
        with self._condition:
            while self._local_claiming and threading.current_thread() is not self._worker:
                self._condition.wait()
        revocation = session.revoke(reason)
        for event in revocation.events:
            self._record_local_start(route, event, stop_event, terminal_reconcile=True)
        failure = session.failure
        with self._condition:
            if failure is None and self._local_feeder is not None:
                failure = self._local_feeder.failure
            receipt = PlaybackReceipt(tuple(self._delivered), reason, route.owner, failure)
            self._terminal_receipt = receipt
            self._last_local_result = (route, receipt)
            if stop_service:
                self._current = self._next = None
            self._local_finalizing = False
            self._local_notification_thread = threading.current_thread()
            self._condition.notify_all()
        try:
            self._notify_local_progress(route, session, stop_event, terminal=True)
            self._notify_finished(receipt, route.effect_owner, route.observer)
        finally:
            with self._condition:
                self._terminal_notification_owner = None
                self._local_notification_thread = None
                self._condition.notify_all()
        return receipt

    def _stop_local_locked(self, reason, *, detach=True):
        if self._stopping:
            return
        self._shutdown_routes = tuple(route for route in (self._current, self._next) if route is not None)
        self._stopped_routes = self._shutdown_routes
        self._shutdown_reason = reason
        self._stopping = True
        self._paused = False
        if detach:
            self._current = self._next = None
        self._condition.notify_all()

    def _skip_local_chunk(self, stream):
        replacement_stop = self._event_factory()
        with self._condition:
            while self._local_transition:
                self._condition.wait()
            route = self._current
            if route is None or route.stream is not stream or self._local_route is not route:
                return None
            if self._terminal_owner == route.owner or self._stopping:
                return CommandResult(False, failure=RuntimeFailure("playback_route_not_found", "Route is terminal"))
            session, old_stop = self._local_session, self._current_stop
            self._local_transition = True
            while self._local_claiming:
                self._condition.wait()
        replacement = None
        failure = None
        try:
            old_stop.set()
            revocation = session.revoke("skip_chunk")
            for event in revocation.events:
                self._record_local_start(route, event, old_stop, terminal_reconcile=True)
            replacement = self._device.open_local_session(route.owner, replacement_stop)
            if replacement is None:
                raise RuntimeError("Local replacement factory declined an owned route")
            if replacement.owner is not route.owner or replacement.stop_event is not replacement_stop:
                raise RuntimeError("Local replacement factory returned the wrong owner or stop epoch")
            replacement.set_wakeup(self._wake_local)
            replacement.share_cleanup(session)
            retained = session.release_unstarted()
            # Transfer ownership before publishing the replacement epoch. A
            # format-changing entry may need retry, so don't arm it here.
            for prepared, audio in retained:
                replacement.adopt(prepared, audio)
            session.retire()
            with self._condition:
                paused = self._paused
            replacement.set_paused(paused)
            with self._condition:
                self._local_session = replacement
                self._current_stop = replacement_stop
                self._local_requeue = list(retained)
                self._condition.notify_all()
            return CommandResult(True)
        except BaseException as exc:
            failure = RuntimeFailure("local_playback_rearm_error", str(exc), exc)
            if replacement is not None:
                replacement.retire()
                with self._condition:
                    self._local_retired_sessions.append(replacement)
        finally:
            with self._condition:
                self._local_transition = False
                self._condition.notify_all()
            # End-effect callbacks may synchronously issue terminal commands.
            # Resources and replacement ownership are settled before re-entry.
            session.flush_retired_effects()
            if replacement is not None:
                replacement.flush_retired_effects()
        self._finalize_local(route, failure.category)
        return CommandResult(False, failure=failure)

    def _close_local(self, route):
        with self._condition:
            if self._local_route is not route:
                return
            while self._local_finalizing or (self._terminal_notification_owner == route.owner
                    and self._local_notification_thread is not threading.current_thread()):
                self._condition.wait()
            session = self._local_session
            retired = tuple(self._local_retired_sessions)
            feeder = self._local_feeder
            if feeder is not None:
                feeder.cancelled = True
                self._condition.notify_all()
        session.retire()
        if feeder is not None and feeder.worker is not None:
            feeder.worker.thread.join()
        for old in retired:
            old.close()
        session.close()
        failure = session.failure
        with self._condition:
            if failure is not None:
                if self._terminal_receipt is not None and self._terminal_receipt.owner == route.owner:
                    self._terminal_receipt = replace(self._terminal_receipt, failure=failure)
                if self._last_local_result is not None and self._last_local_result[0] is route:
                    self._last_local_result = (
                        route,
                        replace(self._last_local_result[1], failure=failure),
                    )
            if self._local_session is session:
                self._local_session = self._local_route = None
                self._local_requeue = []
                self._local_retired_sessions = []
                self._local_feeder = None
                self._local_legacy = False

    def _callback_chunks(self, route: PlaybackRoute, first: object):
        yield first
        while True:
            with self._condition:
                if (
                    self._stopping
                    or self._current is not route
                    or self._terminal_owner == route.owner
                ):
                    return
            handoff = self._next_prepared(route)
            if handoff is None:
                state, reason = self._stream_terminal_state(route.stream)
                if state == "active":
                    continue
                if state == "failed":
                    self._set_terminal(route, reason)
                return
            prepared = getattr(handoff, "chunk", handoff)
            if self.mark_started(prepared, route.owner) and self.commit_started(
                prepared, route.owner
            ) and self.admit_dispatch(prepared, route.owner, self._current_stop):
                yield prepared
            else:
                self._discard_prepared(route.stream, prepared)

    @staticmethod
    def _discard_prepared(stream: object, prepared: object) -> None:
        discard = getattr(stream, "discard_ready", None)
        if callable(discard):
            try:
                discard(prepared)
            except BaseException:
                pass

    def _next_prepared(self, route: PlaybackRoute, *, local=False) -> object | None:
        def admit(candidate: WorkLease) -> object | None:
            if not self._lease_is_current(candidate):
                return None
            with self._condition:
                if (
                    self._stopping
                    or self._current is not route
                    or self._terminal_owner == route.owner
                    or candidate is not route.lease
                ):
                    return None
                return route.owner

        try:
            next_ready = route.stream.next_local_ready if local else route.stream.next_ready
            return next_ready(timeout=0.05, admit_lease=admit)
        except BaseException:
            with self._condition:
                local_claim = self._local_route is route and self._local_claiming
            if local_claim:
                # Release the handoff barrier in _run_local before entering
                # reconciliation; another terminal caller may be waiting on it.
                raise
            self._set_terminal(route, "playback_prepare_error")
            return None

    @staticmethod
    def _stream_terminal_state(stream: object) -> tuple[str, str]:
        failure = getattr(stream, "failure", None)
        if failure is not None:
            return "failed", str(getattr(failure, "category", "playback_prepare_error"))
        if bool(getattr(stream, "cancelled", False)):
            return "cancelled", "speech_cancelled"
        if bool(getattr(stream, "done", False)):
            return "done", "completed"
        return "active", ""

    def _set_terminal(self, route: PlaybackRoute, reason: str) -> None:
        while True:
            if self._finalize_local(route, reason) is not None:
                return
            stop_event = None
            receipt = None
            with self._condition:
                if self._current is not route:
                    return
                if self._local_route is route:
                    continue  # Local publication won the serial-selection race.
                self._terminal_owner = route.owner
                self._terminal_reason = reason
                self._pending_start = None
                self._dispatch_reservation = None
                stop_event = self._current_stop
                receipt = PlaybackReceipt(
                    tuple(self._delivered), reason, route.owner
                )
                self._terminal_receipt = receipt
                self._condition.notify_all()
            break
        stop_event.set()
        self._notify_finished(receipt, route.effect_owner, route.observer)

    def _complete_and_promote(self, route: PlaybackRoute, reason: str, *, local_epoch=None) -> None:
        if self._finalize_local(route, reason, local_epoch=local_epoch) is not None:
            self._close_local(route)
            self._close_route(route)
            next_stop_event = self._event_factory()
            with self._condition:
                self._promote_locked(route, clear_delivered=True, next_stop_event=next_stop_event)
            return
        if local_epoch is not None:
            return
        next_stop_event = self._event_factory()
        receipt = None
        with self._condition:
            if self._current is not route:
                return
            receipt = PlaybackReceipt(tuple(self._delivered), reason, route.owner)
            self._promote_locked(
                route,
                clear_delivered=False,
                next_stop_event=next_stop_event,
            )
        self._notify_finished(receipt, route.effect_owner, route.observer)
        self._close_route(route)

    def _notify_started(
        self,
        chunk: DeliveredChunk,
        effect_owner: RouteEffectOwner | None,
        route_observer: PlaybackObserver | None,
    ) -> None:
        observer = route_observer or self._observer
        if observer is None:
            return
        try:
            if effect_owner is None:
                observer.on_playback_started(chunk)
            else:
                effect_owner.run_step(
                    "playback_observer_started",
                    lambda: observer.on_playback_started(chunk),
                )
        except BaseException:
            pass

    def _notify_audio_started(self, route: PlaybackRoute, prepared: object, stop_event: object) -> None:
        # Device callbacks can race cancellation; never revive a retired owner.
        if stop_event.is_set() or not self._lease_is_current(route.lease):
            return
        index = int(getattr(prepared, "index", -1))
        with self._condition:
            if (self._current is not route or self._stopping
                    or self._terminal_owner == route.owner or self._current_stop is not stop_event):
                return
            delivered = next((chunk for chunk in reversed(self._delivered)
                              if chunk.index == index and chunk.lease == route.lease
                              and chunk.owner_generation == route.owner.generation), None)
        callback = getattr(route.observer or self._observer, "on_audio_started", None)
        if delivered is None or not callable(callback):
            return
        try:
            if route.effect_owner is None:
                callback(delivered)
            else:
                route.effect_owner.run_step("playback_observer_audio_started", lambda: callback(delivered))
        except BaseException:
            pass

    def _notify_waiting(self, route: PlaybackRoute) -> None:
        with self._condition:
            if (self._current is not route or self._stopping or self._paused
                    or self._terminal_owner == route.owner):
                return
        callback = getattr(route.observer or self._observer, "on_playback_waiting", None)
        if not callable(callback):
            return
        try:
            if route.effect_owner is None:
                callback(route.owner)
            else:
                route.effect_owner.run_step("playback_observer_waiting", lambda: callback(route.owner))
        except BaseException:
            pass

    def _notify_finished(
        self,
        receipt: PlaybackReceipt | None,
        effect_owner: RouteEffectOwner | None,
        route_observer: PlaybackObserver | None,
    ) -> None:
        observer = route_observer or self._observer
        if observer is None or receipt is None:
            return
        try:
            if effect_owner is None:
                observer.on_playback_finished(receipt)
            else:
                effect_owner.run_step(
                    "playback_observer_finished",
                    lambda: observer.on_playback_finished(receipt),
                )
        except BaseException:
            pass

    def _notify_paused(self, route: PlaybackRoute) -> None:
        with self._condition:
            if (
                self._current is not route
                or not self._paused
                or self._terminal_owner == route.owner
            ):
                return
        observer = route.observer or self._observer
        callback = getattr(observer, "on_playback_paused", None)
        if not callable(callback):
            return
        try:
            if route.effect_owner is None:
                callback(route.owner)
            else:
                route.effect_owner.run_step(
                    "playback_observer_paused",
                    lambda: callback(route.owner),
                )
        except BaseException:
            pass

    def _cleanup_and_promote(self, route: PlaybackRoute, reason: str) -> None:
        self._close_local(route)
        self._cancel_route(route, reason)
        try:
            self._device.stop(route.owner)
        except BaseException:
            pass
        self._close_route(route)
        next_stop_event = self._event_factory()
        with self._condition:
            if self._current is route:
                self._promote_locked(
                    route,
                    clear_delivered=reason != "completed",
                    next_stop_event=next_stop_event,
                )

    def _cleanup_shutdown(
        self,
        routes: tuple[PlaybackRoute, ...],
        reason: str,
    ) -> None:
        for index, route in enumerate(routes):
            self._close_local(route)
            self._cancel_route(route, reason)
            if index == 0:
                try:
                    self._device.stop(route.owner)
                except BaseException:
                    pass
            self._close_route(route)

    def _cleanup_next(self, reason: str) -> None:
        with self._condition:
            route = self._next
            self._next = None
        self._cancel_route(route, reason)
        self._close_route(route)

    def _promote_locked(
        self,
        route: PlaybackRoute,
        *,
        clear_delivered: bool,
        next_stop_event: object,
    ) -> None:
        if self._current is not route:
            return
        self._current = self._next
        self._next = None
        self._paused = False
        self._current_stop = next_stop_event
        self._pending_start = None
        self._dispatch_reservation = None
        self._terminal_owner = None
        self._terminal_reason = ""
        self._terminal_receipt = None
        if clear_delivered:
            self._delivered.clear()
            self._delivered_keys.clear()
        self._condition.notify_all()

    @staticmethod
    def _route_is_newer(existing: PlaybackRoute, candidate: PlaybackRoute) -> bool:
        existing_generation = getattr(existing.lease.route_generation, "value", -1)
        candidate_generation = getattr(candidate.lease.route_generation, "value", -1)
        return existing_generation > candidate_generation

    def _cancel_route(self, route: PlaybackRoute | None, reason: str) -> None:
        if route is None:
            return
        deadline = time.monotonic() + self._join_timeout_seconds
        with self._condition:
            while self._terminal_notification_owner == route.owner:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        if route.effect_owner is not None:
            route.effect_owner.close()
        try:
            route.stream.cancel(reason)
        except BaseException:
            pass

    @staticmethod
    def _close_route(route: PlaybackRoute | None) -> None:
        if route is None:
            return
        if route.effect_owner is not None:
            route.effect_owner.close()
        close = getattr(route.stream, "close", None)
        if not callable(close):
            return
        try:
            close()
        except BaseException:
            pass

    @staticmethod
    def _route_has_live_producers(route: PlaybackRoute) -> bool:
        predicate = getattr(route.stream, "has_live_producers", None)
        if not callable(predicate):
            return False
        try:
            return bool(predicate())
        except BaseException:
            return True

    def _reset_stopped_state_locked(self, reset_stop_event: object) -> None:
        self._stopping = False
        self._current = None
        self._next = None
        self._paused = False
        self._current_stop = reset_stop_event
        self._terminal_owner = None
        self._terminal_reason = ""
        self._terminal_receipt = None
        self._delivered.clear()
        self._delivered_keys.clear()
        self._pending_start = None
        self._dispatch_reservation = None
        self._shutdown_routes = ()
        self._stopped_routes = ()
        self._shutdown_reason = ""
        self._last_local_result = None
        self._local_requeue = []

    def _ensure_worker(self) -> None:
        with self._condition:
            worker = self._worker
            if worker is not None and worker.is_alive():
                return
            if self._stopping:
                return
            worker = threading.Thread(target=self._run, name="nc-speech-playback", daemon=True)
            self._worker = worker
        worker.start()

    def _ensure_shutdown_worker(self) -> None:
        with self._condition:
            worker = self._worker
            if (
                not self._stopping
                or not self._shutdown_routes
                or (worker is not None and worker.is_alive())
            ):
                return
            worker = threading.Thread(
                target=self._run,
                name="nc-speech-playback-shutdown",
                daemon=True,
            )
            self._worker = worker
        worker.start()


__all__ = [
    "AudioFilePlaybackCapabilities",
    "AudioFilePlaybackDevice",
    "DeliveredChunk",
    "LegacyPlaybackDeviceAdapter",
    "LegacyPlaybackEffectsAdapter",
    "LegacyPlaybackEffectsCapabilities",
    "LegacyNormalSpeechRouteCapabilities",
    "LegacyNormalSpeechSetupCapabilities",
    "LegacyReplayPlaybackSessionCapabilities",
    "LegacyReplayPlaybackSessionFactory",
    "PlaybackDevice",
    "PlaybackOwner",
    "PlaybackObserver",
    "PlaybackReceipt",
    "PlaybackRoute",
    "PlaybackService",
    "PlaybackSnapshot",
    "PreparationEffectAdmission",
    "PreparationEffectGate",
    "prepare_legacy_normal_speech_setup",
    "publish_legacy_normal_speech_route",
    "QueuePlaybackStream",
    "QueuedPlaybackChunk",
    "ReplayPlaybackPipeline",
    "ReplayPlaybackPipelineCapabilities",
    "ReplayPlaybackPreparation",
    "ReplayPlaybackPipelineSession",
    "ReplayPlaybackRuntime",
    "spawn_route_worker",
]
