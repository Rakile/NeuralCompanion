"""Pure speech planning and supervised TTS audio preparation."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import queue
import re
import threading
import time
from types import MappingProxyType
import uuid

from core import runtime_files, runtime_paths, speech_text, text_chunking, text_tags, tts_runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.incremental_audio import IncrementalAudioSource
from core.synthesis_gate import SynthesisGate
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import ScopeClosedError, WorkerHandle, WorkerSupervisor
from core.runtime.controllers import RouteEffectOwner


AdapterResolver = Callable[[RuntimeConfigSnapshot], object | None]
OutputDirectory = Callable[[], str | os.PathLike[str]]
AudioSaver = Callable[[str | os.PathLike[str], object, int], None]
AudioDeleter = Callable[[str | os.PathLike[str]], object]
PathExists = Callable[[str | os.PathLike[str]], bool]
SeedSetter = Callable[[int], None]
Clock = Callable[[], float]
Logger = Callable[[str], None]
Trace = Callable[[str, Mapping[str, object]], None]
SpeechEffect = Callable[[Mapping[str, object]], object]
BeforeChunkPreparation = Callable[["SpeechChunkPlan", CancellationToken], object]
PreparedObserver = Callable[[object], None]
EffectAdmission = Callable[[WorkLease], object | None]
EffectRelease = Callable[[object], None]


def dedupe_adjacent_stream_text(previous: str, current: str) -> tuple[str, bool]:
    """Trim repeated streamed TTS text using the legacy overlap rules."""

    previous_text = str(previous or "").strip()
    current_text = str(current or "").strip()
    if not previous_text or not current_text:
        return current_text, False
    previous_normalized = re.sub(r"\s+", " ", previous_text).strip().lower()
    current_normalized = re.sub(r"\s+", " ", current_text).strip().lower()
    if len(previous_normalized) >= 16 and previous_normalized == current_normalized:
        return "", True
    if len(previous_normalized) >= 24 and current_normalized.startswith(
        previous_normalized
    ):
        # Map the normalized prefix back to its boundary in the current raw
        # text: the previous chunk may use different whitespace widths.
        normalized_size = 0
        for match in re.finditer(r"\s+|\S", current_text):
            raw = match.group()
            normalized_size += 1 if raw.isspace() else len(raw.lower())
            if normalized_size >= len(previous_normalized):
                return current_text[match.end() :].lstrip(" \t\r\n,.;:-"), True

    max_overlap = min(len(previous_text), len(current_text), 160)
    for size in range(max_overlap, 23, -1):
        left = re.sub(r"\s+", " ", previous_text[-size:]).strip().lower()
        right = re.sub(r"\s+", " ", current_text[:size]).strip().lower()
        if left and left == right:
            return current_text[size:].lstrip(" \t\r\n,.;:-"), True
    return current_text, False


def normalize_generated_chunk(result, default_payload_path=None) -> dict[str, object]:
    """Normalize legacy addon/TTS generation results into the stable chunk shape."""

    if isinstance(result, Mapping):
        normalized = dict(result)
        normalized.setdefault("ok", True)
        normalized.setdefault("kind", "audio")
        return normalized
    if result:
        normalized: dict[str, object] = {"ok": True, "kind": "audio"}
        if default_payload_path:
            normalized["payload_path"] = default_payload_path
        return normalized
    return {"ok": False, "kind": "audio"}


def _missing_adapter(_snapshot: RuntimeConfigSnapshot) -> object | None:
    return None


def _default_output_directory() -> Path:
    return runtime_paths.runtime_temp_dir("tts")


def _default_delete_audio(path) -> None:
    runtime_files.safe_delete_with_retry(path, logger=lambda _message: None)


def _quiet_logger(_message: str) -> None:
    return None


def _quiet_trace(_event: str, _fields: Mapping[str, object]) -> None:
    return None


def _quiet_effect(_payload: Mapping[str, object]) -> object:
    return None


def _default_effect_admission(lease: WorkLease) -> object:
    return lease


def _default_effect_release(_admission: object) -> None:
    return None


def _record_performance(event, **fields):
    """Optional metadata capture must never affect speech ownership or output."""
    try:
        from core.speech_performance import record_event
        record_event(event, **fields)
    except BaseException:
        pass


@dataclass(frozen=True, slots=True)
class SpeechOutputCapabilities:
    """Explicit effectful dependencies used only during preparation."""

    adapter_for: AdapterResolver = _missing_adapter
    output_directory: OutputDirectory = _default_output_directory
    save_audio: AudioSaver = tts_runtime.save_audio_file
    delete_audio: AudioDeleter = _default_delete_audio
    path_exists: PathExists = os.path.exists
    set_seed: SeedSetter | None = None
    clock: Clock = time.monotonic
    logger: Logger = _quiet_logger
    trace: Trace = _quiet_trace
    generation_started: SpeechEffect = _quiet_effect
    generation_finished: SpeechEffect = _quiet_effect
    audio_chunk_ready: SpeechEffect = _quiet_effect
    prepare_playback_audio: Callable[[object, RuntimeConfigSnapshot], object] | None = None
    incremental_pcm_allowed: Callable[[SpeechChunkPlan, RuntimeConfigSnapshot], bool] | None = None


def _freeze_value(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _frozen_metadata(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(
        {str(key): _freeze_value(item) for key, item in dict(value or {}).items()}
    )


@dataclass(frozen=True, slots=True)
class SpeechChunkPlan:
    index: int
    text: str
    expression: str
    voice_action: str | None = None
    voice_path: str = ""
    voice_language: str = ""
    source_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class SpeechPlan:
    source_text: str
    chunks: tuple[SpeechChunkPlan, ...]
    config: RuntimeConfigSnapshot
    terminal_expression: str


@dataclass(frozen=True, slots=True)
class PreparedAudioChunk:
    speech_id: str
    index: int
    text: str
    expression: str
    voice_action: str | None
    audio_path: str
    sample_rate: int
    lease: WorkLease
    source_metadata: Mapping[str, object]
    generation_started_at: float
    generation_duration_ms: float
    audio_save_duration_ms: float
    ready_at: float = 0.0
    first_ready_ms: float = 0.0
    inter_chunk_ready_ms: float = 0.0
    playback_audio: object | None = None
    audio_source: IncrementalAudioSource | None = None


@dataclass(frozen=True, slots=True)
class PreparedAudioHandoff:
    """A prepared chunk irreversibly admitted against token and exact lease."""

    chunk: PreparedAudioChunk
    lease_admission: object


class SpeechOutputStream:
    """Bounded ordered handoff for generated chunks; yielded files transfer ownership."""

    def __init__(
        self,
        *,
        speech_id: str,
        lease: WorkLease,
        token: CancellationToken,
        max_buffer_chunks: int,
        clock: Clock,
        delete_audio: AudioDeleter,
        cancel_callback: Callable[["SpeechOutputStream", str], None],
        close_callback: Callable[["SpeechOutputStream"], None],
    ) -> None:
        self.speech_id = str(speech_id)
        self.lease = lease
        self.token = token
        self.max_buffer_chunks = max(1, int(max_buffer_chunks))
        self._clock = clock
        self._delete_audio = delete_audio
        self._cancel_callback = cancel_callback
        self._close_callback = close_callback
        self._started_at = clock()
        self._last_ready_at: float | None = None
        self._buffer: deque[PreparedAudioChunk] = deque()
        self._condition = threading.Condition()
        self._handoff_reserved = False
        self._publish_reserved = False
        self._handles: list[WorkerHandle] = []
        self._preparation_started = False
        self._generation_reservations = {}
        self._done = False
        self._cancelled = False
        self._closed = False
        self._failure: RuntimeFailure | None = None
        self._high_watermark = 0

    @property
    def done(self) -> bool:
        with self._condition:
            return self._done

    @property
    def cancelled(self) -> bool:
        with self._condition:
            cancelled = self._cancelled
        return cancelled or self.token.cancelled

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    @property
    def failure(self) -> RuntimeFailure | None:
        with self._condition:
            return self._failure

    @property
    def high_watermark(self) -> int:
        with self._condition:
            return self._high_watermark

    def next_ready(
        self,
        timeout: float | None = None,
        *,
        admit_lease: Callable[[WorkLease], object | None] | None = None,
    ) -> PreparedAudioChunk | PreparedAudioHandoff | None:
        deadline = None if timeout is None else self._clock() + max(0.0, float(timeout))
        prepared = self._reserve_next_ready(deadline)
        if prepared is None:
            return None

        lease_admission = None
        admitted = False
        try:
            if admit_lease is None:
                lease_admission = self
            else:
                lease_admission = admit_lease(prepared.lease)
            exact_lease = (
                admit_lease is None
                or getattr(lease_admission, "lease", None) is prepared.lease
            )
            with self.token.admission_scope() as token_admitted:
                if token_admitted and lease_admission is not None and exact_lease:
                    with self._condition:
                        if not self._cancelled and not self._closed:
                            self._handoff_reserved = False
                            self._condition.notify_all()
                            admitted = (prepared.audio_source is None
                                        or prepared.audio_source.handoff())
        except BaseException:
            self._reject_reserved_handoff(
                prepared,
                "speech_handoff_admission_failed",
            )
            raise

        if admitted:
            if admit_lease is None:
                return prepared
            return PreparedAudioHandoff(prepared, lease_admission)

        reason = self.token.reason or "stale_prepared_lease"
        self._reject_reserved_handoff(prepared, reason)
        return None

    def _reserve_next_ready(
        self,
        deadline: float | None,
    ) -> PreparedAudioChunk | None:
        while True:
            with self._condition:
                if self._cancelled or self._closed:
                    return None
                if not self._handoff_reserved and self._buffer:
                    self._handoff_reserved = True
                    return self._buffer.popleft()
                if self._done and not self._buffer:
                    return None
                wait_without_deadline = deadline is None

            if self.token.cancelled:
                self._reject_reserved_handoff(
                    None,
                    self.token.reason or "speech_cancelled",
                )
                return None
            if wait_without_deadline:
                remaining = None
            else:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return None

            with self._condition:
                if self._cancelled or self._closed:
                    return None
                if not self._handoff_reserved and self._buffer:
                    continue
                if self._done and not self._buffer:
                    return None
                self._condition.wait(remaining)

    def _reject_reserved_handoff(
        self,
        prepared: PreparedAudioChunk | None,
        reason: str,
    ) -> None:
        with self._condition:
            self._handoff_reserved = False
            self._cancelled = True
            buffered = tuple(self._buffer)
            self._buffer.clear()
            self._condition.notify_all()
        self.token.cancel(str(reason or "speech_cancelled"))
        self._cancel_callback(self, str(reason or "speech_cancelled"))
        if prepared is not None:
            self.discard_ready(prepared)
        for chunk in buffered:
            self.discard_ready(chunk)

    def cancel(self, reason: str = "speech_cancelled") -> None:
        self._cancel_callback(self, str(reason or "speech_cancelled"))

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            needs_cancel = not self._done
            self._closed = True
            buffered = tuple(self._buffer)
            self._buffer.clear()
            self._condition.notify_all()
        self._discard_unclaimed_generation()
        if needs_cancel:
            self._cancel_callback(self, "speech_stream_closed")
        for prepared in buffered:
            self.discard_ready(prepared)
        self._close_callback(self)

    def ready_chunks(self) -> tuple[PreparedAudioChunk, ...]:
        """Return immutable buffered lookahead without reserving a handoff."""

        with self._condition:
            return tuple(self._buffer)

    def discard_ready(self, prepared: object) -> None:
        source = getattr(prepared, 'audio_source', None)
        if source is not None:
            source.close()
        path = str(getattr(prepared, "audio_path", "") or "")
        if path:
            self._delete_safely(path)

    def _add_handle(self, handle: WorkerHandle) -> None:
        with self._condition:
            self._handles.append(handle)

    def _claim_preparation_start(self) -> bool:
        with self._condition:
            if self._preparation_started or self._cancelled or self._closed:
                return False
            self._preparation_started = True
            return True

    def _handles_snapshot(self) -> tuple[WorkerHandle, ...]:
        with self._condition:
            return tuple(self._handles)

    def _publish(self, prepared: PreparedAudioChunk) -> bool:
        while True:
            with self._condition:
                if self._done or self._cancelled or self._closed:
                    return False
                if (
                    not self._publish_reserved
                    and self._occupied_slots_locked() < self.max_buffer_chunks
                ):
                    self._publish_reserved = True
                    break
                self._condition.wait(0.05)
            if self.token.cancelled:
                return False
        try:
            ready_at = self._clock()
        except BaseException:
            with self._condition:
                self._publish_reserved = False
                self._condition.notify_all()
            raise
        with self.token.admission_scope() as token_admitted:
            if not token_admitted:
                with self._condition:
                    self._publish_reserved = False
                    self._condition.notify_all()
                return False
            with self._condition:
                if self._done or self._cancelled or self._closed:
                    self._publish_reserved = False
                    self._condition.notify_all()
                    return False
                first_ready_ms = 0.0
                inter_chunk_ready_ms = 0.0
                if self._last_ready_at is None:
                    first_ready_ms = max(0.0, (ready_at - self._started_at) * 1000.0)
                else:
                    inter_chunk_ready_ms = max(0.0, (ready_at - self._last_ready_at) * 1000.0)
                prepared = replace(
                    prepared,
                    ready_at=ready_at,
                    first_ready_ms=first_ready_ms,
                    inter_chunk_ready_ms=inter_chunk_ready_ms,
                )
                self._last_ready_at = ready_at
                self._buffer.append(prepared)
                self._publish_reserved = False
                self._high_watermark = max(self._high_watermark, len(self._buffer))
                self._condition.notify_all()
                return True

    def _occupied_slots_locked(self) -> int:
        return (
            len(self._buffer)
            + int(self._handoff_reserved)
            + int(self._publish_reserved)
        )

    def _discard_unclaimed_generation(self):
        for reservation in self._generation_reservations.values():
            reservation.discard_unclaimed()

    def _mark_done(self) -> None:
        with self._condition:
            self._done = True
            self._condition.notify_all()
        self._discard_unclaimed_generation()

    def _mark_failure(self, failure: RuntimeFailure) -> None:
        with self._condition:
            if self._failure is None:
                self._failure = failure
            self._done = True
            self._condition.notify_all()
        self._discard_unclaimed_generation()

    def _cancel_from_service(self, reason: str) -> tuple[PreparedAudioChunk, ...]:
        self.token.cancel(reason)
        with self._condition:
            self._cancelled = True
            buffered = tuple(self._buffer)
            self._buffer.clear()
            self._condition.notify_all()
        self._discard_unclaimed_generation()
        return buffered

    def _delete_safely(self, path: str) -> None:
        try:
            self._delete_audio(path)
        except BaseException:
            pass


class SpeechOutputService:
    """Own deterministic planning and generation-only speech preparation."""

    name = "speech_output"

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        capabilities: SpeechOutputCapabilities | None = None,
        prepared_observer: PreparedObserver | None = None,
        admit_prepared_effect: EffectAdmission = _default_effect_admission,
        release_prepared_effect: EffectRelease = _default_effect_release,
    ) -> None:
        self._workers = workers
        self._capabilities = capabilities or SpeechOutputCapabilities()
        self._lock = threading.Lock()
        self._generation_gate = SynthesisGate()
        self._voice_warmup_lock = threading.Lock()
        self._voice_warmup_cache: set[tuple[str, str]] = set()
        self._voice_warmup_pending: set[tuple[str, str]] = set()
        self._streams: dict[str, SpeechOutputStream] = {}
        self._incremental_sources: dict[IncrementalAudioSource, str] = {}
        self._accepting = True
        self._private_continuous_audio: dict[str, dict] = {}
        self._private_continuous_active: set[str] = set()
        self._prepared_observer = prepared_observer
        self._admit_prepared_effect = admit_prepared_effect
        self._release_prepared_effect = release_prepared_effect

    @property
    def workers(self) -> WorkerSupervisor:
        return self._workers

    def activity_snapshot(self) -> Mapping[str, object]:
        """Read-only activity for document indexing; includes streaming gaps."""
        with self._lock:
            active = len(set(self._streams) | set(self._incremental_sources.values()))
        with self._voice_warmup_lock:
            warmups = len(self._voice_warmup_pending)
        return {"active_speech": active, "speech_warmups": warmups}

    def start(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = True
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = False
            self._private_continuous_audio.clear()
            self._private_continuous_active.clear()
            streams = tuple(self._streams.values())
            sources = tuple(self._incremental_sources)
        for source in sources:
            source.cancel('runtime_shutdown')
            source.close()
        for stream in streams:
            self._cancel_stream(stream, "runtime_shutdown")
            stream.close()
        return CommandResult(True)

    def prepare_private_continuous(
        self, stage_id: str, plan: SpeechPlan, token: CancellationToken,
    ) -> bool:
        """Pre-synthesize up to two chunks without files, events, or playback."""
        if (not isinstance(stage_id, str) or len(stage_id) != 32
                or not isinstance(plan, SpeechPlan) or token.cancelled):
            return False
        with self._lock:
            if not self._accepting:
                return False
            self._private_continuous_audio[stage_id] = dict(
                revision=plan.config.revision, token=token, chunks={},
                created_at=self._capabilities.clock())
            self._prune_private_continuous_locked()
        completed = False
        try:
            adapter = self._capabilities.adapter_for(plan.config)
            sample_rate = int(adapter.sr)
            for chunk in plan.chunks[:2]:
                acquired = False
                while not token.cancelled and self._accepting:
                    acquired = self._generation_gate.acquire(timeout=.05)
                    if acquired:
                        break
                if not acquired:
                    return False
                try:
                    kwargs = self._generation_kwargs(plan, chunk)
                    spoken_text = self._spoken_text(chunk)
                    wav = adapter.generate(spoken_text, **kwargs)
                    with self._lock:
                        entry = self._private_continuous_audio.get(stage_id)
                        if entry is None or token.cancelled or not self._accepting:
                            return False
                        key = self._private_chunk_key(chunk, sample_rate, spoken_text)
                        entry['chunks'].setdefault(key, deque()).append(wav)
                finally:
                    self._generation_gate.release()
            completed = True
            return True
        except Exception:
            return False
        finally:
            if not completed:
                self.discard_private_continuous(stage_id)

    def activate_private_continuous(self, stage_id: str) -> None:
        with self._lock:
            self._private_continuous_active.add(stage_id)

    def discard_private_continuous(self, stage_id: str) -> None:
        with self._lock:
            self._private_continuous_active.discard(stage_id)
            self._private_continuous_audio.pop(stage_id, None)

    def _prune_private_continuous_locked(self) -> None:
        now = self._capabilities.clock()
        for stage_id, entry in tuple(self._private_continuous_audio.items()):
            if entry['token'].cancelled or now - entry['created_at'] >= 300:
                self._private_continuous_audio.pop(stage_id, None)
                self._private_continuous_active.discard(stage_id)
        while len(self._private_continuous_audio) > 4:
            stage_id = next(iter(self._private_continuous_audio))
            self._private_continuous_audio.pop(stage_id, None)
            self._private_continuous_active.discard(stage_id)

    @staticmethod
    def _private_chunk_key(chunk: SpeechChunkPlan, sample_rate: int, spoken_text: str) -> tuple:
        return (spoken_text, chunk.voice_path, chunk.voice_language,
                chunk.voice_action, int(sample_rate))

    @staticmethod
    def _spoken_text(chunk: SpeechChunkPlan) -> str:
        return (speech_text.separate_speech_compounds(chunk.text)
                if chunk.source_metadata.get('remote_capture_id') else chunk.text)

    def _private_audio_for(self, plan: SpeechPlan, chunk: SpeechChunkPlan,
                           sample_rate: int, spoken_text: str):
        stage_id = chunk.source_metadata.get('continuous_stage_id')
        if not isinstance(stage_id, str):
            return None
        with self._lock:
            self._prune_private_continuous_locked()
            entry = self._private_continuous_audio.get(stage_id)
            if (stage_id not in self._private_continuous_active or entry is None
                    or entry['revision'] != plan.config.revision or entry['token'].cancelled):
                return None
            available = entry['chunks'].get(self._private_chunk_key(chunk, sample_rate, spoken_text))
            return available.popleft() if available else None

    def _generation_kwargs(self, plan: SpeechPlan, chunk: SpeechChunkPlan) -> dict:
        kwargs = tts_runtime.build_generation_kwargs(
            plan.config.values, set_seed=self._capabilities.set_seed,
            path_exists=self._capabilities.path_exists, logger=self._capabilities.logger)
        if chunk.voice_path:
            kwargs['audio_prompt_path'] = chunk.voice_path
        backend = str(plan.config.values.get('tts_backend', '') or '').strip().lower().replace('-', '_')
        if backend == 'pocket_tts':
            backend = 'pockettts'
        if chunk.voice_language and backend in {'pockettts', 'pockettts_multilingual'}:
            kwargs['pocket_tts_language'] = chunk.voice_language
        return kwargs

    def plan(
        self,
        text: str,
        config: RuntimeConfigSnapshot,
        *,
        start_index: int = 0,
        initial_expression: str = "neutral",
        preserve_input_chunk: bool = False,
        voice_path: str = "",
        voice_language: str = "",
        source_metadata: Mapping[str, object] | None = None,
        prepared_sentence_splitter: text_chunking.PreparedSentenceSplitter | None = None,
    ) -> SpeechPlan:
        """Return a deterministic plan without invoking any effectful capability."""

        frozen_config = RuntimeConfigSnapshot(
            revision=int(config.revision),
            values=_frozen_metadata(config.values),
        )
        values = frozen_config.values
        available_emotions = tuple(
            str(item or "").strip().lower()
            for item in values.get(
                "speech_available_emotion_names",
                ("neutral", "happy", "sad", "angry", "shy", "surprised"),
            )
            if str(item or "").strip()
        )
        supported_actions = self._supported_actions(values)
        available_emotions = tuple(set(available_emotions) | text_tags.persona_mood_names(values))
        sanitized = speech_text.sanitize_assistant_text_for_speech(
            str(text or ""),
            preserve_emotion_tags=True,
            normalize_bracket_tag=text_tags.normalize_bracket_tag,
            is_sound_tag=lambda tag: str(tag or "").strip().lower() in supported_actions,
            is_emotion_tag=lambda tag: text_tags.is_emotion_tag(tag, available_emotions),
        )
        segments = text_tags.parse_speech_action_segments(
            sanitized,
            available_emotions,
            supported_actions,
            initial_emotion=initial_expression,
        )
        avatar_mode = str(values.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
        if avatar_mode == "musetalk":
            segments = self._coalesce_musetalk_segments(segments, values)

        next_index = max(0, int(start_index or 0))
        metadata = dict(source_metadata or {})
        replay_mode = bool(metadata.get("tts_replay") or metadata.get("replay"))
        chunks: list[SpeechChunkPlan] = []
        source_chunk_index = 0
        terminal_expression = str(initial_expression or "neutral").strip().lower() or "neutral"
        for expression, voice_action, segment_text in segments:
            terminal_expression = str(expression or terminal_expression).strip().lower() or terminal_expression
            raw_segment = str(segment_text or "").strip()
            if not raw_segment:
                continue
            if preserve_input_chunk:
                segment_chunks = [raw_segment]
            elif avatar_mode == "musetalk" or (
                avatar_mode == "ditto" and not bool(values.get("stream_mode", False))
            ):
                segment_chunks = text_chunking.progressive_chunk_text(
                    raw_segment,
                    start_chunk_index=next_index,
                    limit_getter=lambda index: self._musetalk_limits(values, index),
                    min_chunk_size=self._minimum_chunk_size(values),
                    logger=lambda _message: None,
                )
            else:
                target, maximum = self._standard_limits(values)
                splitter = (
                    prepared_sentence_splitter
                    or text_chunking.IO_FREE_SENTENCE_SPLITTER
                )
                segment_chunks = text_chunking.chunk_text(
                    raw_segment,
                    target,
                    maximum,
                    min_chunk_size=self._minimum_chunk_size(values),
                    sentence_splitter=splitter.split,
                    logger=lambda _message: None,
                )
            if not segment_chunks:
                segment_chunks = [raw_segment]
            for local_index, chunk_text in enumerate(segment_chunks):
                clean_text = str(chunk_text or "").strip()
                if not clean_text:
                    continue
                chunk_metadata = dict(metadata)
                first_source_chunk = source_chunk_index == 0
                chunk_metadata["replay_message_first_chunk"] = bool(
                    replay_mode and first_source_chunk
                )
                chunk_metadata["tts_source_first_chunk"] = first_source_chunk
                if not first_source_chunk:
                    chunk_metadata["story_audio_cues"] = ()
                chunks.append(
                    SpeechChunkPlan(
                        index=next_index,
                        text=clean_text,
                        expression=terminal_expression,
                        voice_action=(
                            str(voice_action or "").strip().lower() or None
                            if local_index == 0
                            else None
                        ),
                        voice_path=str(voice_path or "").strip(),
                        voice_language=str(voice_language or "").strip().lower(),
                        source_metadata=_frozen_metadata(chunk_metadata),
                    )
                )
                next_index += 1
                source_chunk_index += 1
        return SpeechPlan(
            source_text=str(text or ""),
            chunks=tuple(chunks),
            config=frozen_config,
            terminal_expression=terminal_expression,
        )

    def prepare(
        self,
        plan: SpeechPlan,
        lease: WorkLease,
        token: CancellationToken,
        *,
        before_chunk: BeforeChunkPreparation | None = None,
        start: bool = True,
        route_effect_owner: RouteEffectOwner | None = None,
        generation_order=None,
    ) -> SpeechOutputStream:
        values = plan.config.values
        max_buffer_chunks = max(
            1,
            min(64, int(values.get("tts_prepare_buffer_chunks", 6) or 6)),
        )
        speech_id = uuid.uuid4().hex
        stream = SpeechOutputStream(
            speech_id=speech_id,
            lease=lease,
            token=token,
            max_buffer_chunks=max_buffer_chunks,
            clock=self._capabilities.clock,
            delete_audio=self._capabilities.delete_audio,
            cancel_callback=self._cancel_stream,
            close_callback=self._close_stream,
        )
        if generation_order is not None:
            stream._generation_reservations = dict(zip(
                (chunk.index for chunk in plan.chunks), generation_order.reserve(len(plan.chunks))))
        with self._lock:
            if not self._accepting:
                stream._mark_failure(
                    RuntimeFailure(
                        "speech_output_stopped",
                        "Speech preparation is not accepting work",
                    )
                )
                return stream
            self._streams[speech_id] = stream
        if not plan.chunks or token.cancelled:
            if token.cancelled:
                stream._cancel_from_service(token.reason or "speech_cancelled")
            stream._mark_done()
            return stream
        if start:
            self.start_preparation(
                stream,
                plan,
                before_chunk=before_chunk,
                route_effect_owner=route_effect_owner,
            )
        return stream

    def start_preparation(
        self,
        stream: SpeechOutputStream,
        plan: SpeechPlan,
        *,
        before_chunk: BeforeChunkPreparation | None = None,
        route_effect_owner: RouteEffectOwner | None = None,
    ) -> CommandResult[None]:
        if not stream._claim_preparation_start():
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "speech_preparation_stale",
                    "Speech preparation is already started or no longer active.",
                ),
            )
        try:
            if route_effect_owner is None:
                handle = self._workers.spawn(
                    name="nc-tts-prepare",
                    lease=stream.lease,
                    target=lambda worker_token: self._run_preparation(
                        stream,
                        plan,
                        worker_token,
                        before_chunk,
                        None,
                    ),
                    identity=("speech_output", stream.speech_id),
                )
            else:
                spawned = route_effect_owner.run_step(
                    "nc-tts-prepare_spawn",
                    lambda: self._workers.spawn(
                        name="nc-tts-prepare",
                        lease=stream.lease,
                        target=lambda worker_token: self._run_preparation(
                            stream,
                            plan,
                            worker_token,
                            before_chunk,
                            None,
                        ),
                        identity=("speech_output", stream.speech_id),
                    ),
                )
                if not spawned.accepted or spawned.value is None:
                    failure = spawned.failure or RuntimeFailure(
                        "route_effect_stale",
                        "Speech preparation lost exact route authority.",
                    )
                    stream._mark_failure(failure)
                    return CommandResult(False, failure=failure)
                handle = spawned.value
            stream._add_handle(handle)
            return CommandResult(True)
        except ScopeClosedError as exc:
            failure = RuntimeFailure(
                "speech_output_scope_closed",
                "Speech preparation scope is closing",
                exc,
            )
        except BaseException as exc:
            failure = RuntimeFailure(
                "speech_output_worker_start_failed",
                f"Could not start speech preparation: {exc}",
                exc,
            )
        stream._mark_failure(failure)
        return CommandResult(False, failure=failure)

    def cancel(self, speech_id: str, reason: str) -> CommandResult[None]:
        with self._lock:
            stream = self._streams.get(str(speech_id or ""))
            sources = tuple(source for source, owner_id in self._incremental_sources.items()
                            if owner_id == str(speech_id or ""))
        if stream is None and sources:
            for source in sources:
                source.cancel(str(reason or "speech_cancelled"))
                source.close()
            return CommandResult(True)
        if stream is None:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "speech_output_not_found",
                    "Speech preparation is not active",
                ),
            )
        self._cancel_stream(stream, str(reason or "speech_cancelled"))
        return CommandResult(True)

    def warm_voice_paths(
        self,
        config: RuntimeConfigSnapshot,
        lease: WorkLease,
        voice_paths,
        token: CancellationToken,
    ) -> CommandResult[tuple[str, ...]]:
        """Warm uncached replay voices on one supervised, bounded worker."""

        backend = str(config.values.get("tts_backend", "") or "").strip().lower()
        requested = tuple(
            dict.fromkeys(
                str(path or "").strip()
                for path in tuple(voice_paths or ())
                if str(path or "").strip()
            )
        )
        if not requested or token.cancelled:
            return CommandResult(True, ())
        with self._voice_warmup_lock:
            planned = tuple(
                path
                for path in requested
                if (backend, path) not in self._voice_warmup_cache
                and (backend, path) not in self._voice_warmup_pending
            )
            self._voice_warmup_pending.update((backend, path) for path in planned)
        if not planned:
            return CommandResult(True, ())

        completed: list[str] = []
        failure: list[BaseException] = []

        def warm(worker_token: CancellationToken) -> None:
            try:
                adapter = self._capabilities.adapter_for(config)
                generator = getattr(adapter, "generate", None)
                if not callable(generator):
                    return
                for path in planned:
                    if token.cancelled or worker_token.cancelled:
                        return
                    gate_acquired = False
                    while not token.cancelled and not worker_token.cancelled:
                        gate_acquired = self._generation_gate.acquire(timeout=0.05)
                        if gate_acquired:
                            break
                    if not gate_acquired:
                        return
                    try:
                        kwargs = tts_runtime.build_generation_kwargs(
                            config.values,
                            set_seed=self._capabilities.set_seed,
                            path_exists=self._capabilities.path_exists,
                            logger=self._capabilities.logger,
                        )
                        kwargs["audio_prompt_path"] = path
                        generator("Ready.", **kwargs)
                    finally:
                        self._generation_gate.release()
                    with self._voice_warmup_lock:
                        self._voice_warmup_cache.add((backend, path))
                    completed.append(path)
                    self._capabilities.logger(
                        f"Replay voice warmup complete: {Path(path).name}"
                    )
            except BaseException as exc:
                failure.append(exc)
                self._capabilities.logger(
                    f"Replay voice warmup failed: {exc}"
                )
            finally:
                with self._voice_warmup_lock:
                    for path in planned:
                        self._voice_warmup_pending.discard((backend, path))

        try:
            handle = self._workers.spawn(
                name="nc-replay-voice-warmup",
                lease=lease,
                target=warm,
                identity=("speech_output", "replay_voice_warmup", backend, planned),
            )
        except BaseException as exc:
            with self._voice_warmup_lock:
                for path in planned:
                    self._voice_warmup_pending.discard((backend, path))
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "replay_voice_warmup_start_failed",
                    f"Could not start replay voice warmup: {exc}",
                    exc,
                ),
            )
        self._workers.join_handles((handle,))
        if handle.timed_out:
            self._workers.cancel_handles((handle,), "replay_voice_warmup_timeout")
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "replay_voice_warmup_timeout",
                    "Replay voice warmup exceeded the supervised worker deadline",
                ),
            )
        if token.cancelled:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "replay_cancelled",
                    token.reason or "Replay was cancelled during voice warmup",
                ),
            )
        if failure:
            return CommandResult(
                False,
                failure=RuntimeFailure(
                    "replay_voice_warmup_failed",
                    str(failure[0]) or "Replay voice warmup failed",
                    failure[0],
                ),
            )
        return CommandResult(True, tuple(completed))

    @staticmethod
    def _minimum_chunk_size(values: Mapping[str, object]) -> int:
        return max(1, int(values.get("speech_min_chunk_size", 10) or 10))

    @staticmethod
    def _supported_actions(values: Mapping[str, object]) -> tuple[str, ...]:
        configured = values.get("speech_supported_sound_tag_names")
        if configured is not None:
            return tuple(
                str(item or "").strip().lower()
                for item in configured
                if str(item or "").strip()
            )
        backend = str(values.get("tts_backend", "") or "").strip().lower()
        if backend in {"chatterbox", "chatterbox_multilingual"}:
            return tuple(sorted(text_tags.SOUND_TAG_NAMES))
        return ()

    @staticmethod
    def _standard_limits(values: Mapping[str, object]) -> tuple[int, int]:
        if bool(values.get("stream_mode", False)):
            target = int(values.get("stream_chunk_target_chars", 80) or 80)
            maximum = int(values.get("stream_chunk_max_chars", 185) or 185)
        else:
            target = int(values.get("chunk_target_chars", 100) or 100)
            maximum = int(values.get("chunk_max_chars", 200) or 200)
        return target, maximum

    @staticmethod
    def _musetalk_limits(values: Mapping[str, object], index: int) -> tuple[int, int]:
        chunk_index = max(0, int(index or 0))
        if chunk_index == 0:
            pair = (
                int(values.get("musetalk_quickstart_1_target_chars", 170) or 170),
                int(values.get("musetalk_quickstart_1_max_chars", 320) or 320),
            )
        elif chunk_index == 1:
            pair = (
                int(values.get("musetalk_quickstart_2_target_chars", 130) or 130),
                int(values.get("musetalk_quickstart_2_max_chars", 240) or 240),
            )
        else:
            pair = (
                int(values.get("musetalk_chunk_target_chars", 110) or 110),
                int(values.get("musetalk_chunk_max_chars", 220) or 220),
            )
        return pair

    @staticmethod
    def _coalesce_musetalk_segments(segments, values):
        normalized = [
            (expression, action, str(segment or "").strip())
            for expression, action, segment in segments
            if str(segment or "").strip()
        ]
        combined = []
        index = 0
        while index < len(normalized):
            _expression, action, text = normalized[index]
            # Apply the same narrow rule throughout the reply, including streams.
            # Spoken phrases such as "Hmm" or "[gasp] Really!" keep their boundary.
            if index + 1 < len(normalized):
                next_expression, next_action, next_text = normalized[index + 1]
                if (
                    action is not None
                    and text_tags.normalize_bracket_tag(text) == action
                    and next_action is None
                    and any(character.isalnum() for character in next_text)
                ):
                    combined.append((next_expression, action, f"{text} {next_text}"))
                    index += 2
                    continue
            combined.append(normalized[index])
            index += 1
        return combined

    def _run_preparation(
        self,
        stream: SpeechOutputStream,
        plan: SpeechPlan,
        worker_token: CancellationToken,
        before_chunk: BeforeChunkPreparation | None,
        route_effect_owner: RouteEffectOwner | None,
    ) -> None:
        addon_events = bool(
            plan.chunks
            and plan.chunks[0].source_metadata.get("publish_tts_addon_events", False)
        )
        generation_payload = {
            "trace_id": str(
                plan.chunks[0].source_metadata.get("tts_trace_id", "") or ""
            )
            if plan.chunks
            else "",
            "tts_backend": str(plan.config.values.get("tts_backend", "") or ""),
            "replay": bool(
                plan.chunks
                and plan.chunks[0].source_metadata.get("tts_replay", False)
            ),
        }
        if addon_events:
            self._effect_with_admission(
                stream.lease,
                self._capabilities.generation_started,
                generation_payload,
            )
        try:
            adapter = self._capabilities.adapter_for(plan.config)
            if adapter is None:
                stream._mark_failure(
                    RuntimeFailure(
                        "tts_adapter_unavailable",
                        "The configured TTS adapter is unavailable",
                    )
                )
                return
            output_directory = Path(self._capabilities.output_directory())
            sample_rate = int(getattr(adapter, "sr", 24000) or 24000)
            worker_count = max(
                1,
                min(4, int(plan.config.values.get("tts_prepare_workers", 1) or 1)),
            )
            if callable(before_chunk):
                before_chunk(plan.chunks[0], worker_token)
            first = self._generate_chunk(
                stream,
                plan,
                plan.chunks[0],
                adapter,
                sample_rate,
                output_directory,
                worker_token,
            )
            if first is None:
                return
            self._notify_prepared_observer(first)
            if not stream._publish(first):
                stream.discard_ready(first)
                return
            remaining = plan.chunks[1:]
            if worker_count == 1:
                for chunk in remaining:
                    if callable(before_chunk):
                        before_chunk(chunk, worker_token)
                    prepared = self._generate_chunk(
                        stream,
                        plan,
                        chunk,
                        adapter,
                        sample_rate,
                        output_directory,
                        worker_token,
                    )
                    if prepared is None:
                        return
                    self._notify_prepared_observer(prepared)
                    if not stream._publish(prepared):
                        stream.discard_ready(prepared)
                        return
            elif remaining:
                self._prepare_parallel(
                    stream,
                    plan,
                    remaining,
                    adapter,
                    sample_rate,
                    output_directory,
                    worker_token,
                    worker_count,
                    before_chunk,
                    route_effect_owner,
                )
        except BaseException as exc:
            # Skip/Stop wakes pending PCM readiness with InterruptedError.
            # Treat an owned cancellation as retirement, while real errors remain visible.
            if isinstance(exc, InterruptedError) and self._stopping(stream, worker_token):
                return
            self._capabilities.logger(f"Speech preparation failed: {exc}")
            stream._mark_failure(
                RuntimeFailure(
                    "tts_preparation_failed",
                    f"Speech preparation failed: {exc}",
                    exc,
                )
            )
        finally:
            if addon_events and not stream.cancelled:
                self._effect_with_admission(
                    stream.lease,
                    self._capabilities.generation_finished,
                    generation_payload,
                )
            stream._mark_done()

    def _prepare_parallel(
        self,
        stream: SpeechOutputStream,
        plan: SpeechPlan,
        chunks: tuple[SpeechChunkPlan, ...],
        adapter,
        sample_rate: int,
        output_directory: Path,
        coordinator_token: CancellationToken,
        worker_count: int,
        before_chunk: BeforeChunkPreparation | None,
        route_effect_owner: RouteEffectOwner | None,
    ) -> None:
        completions: queue.Queue[tuple[int, PreparedAudioChunk | None, BaseException | None]] = queue.Queue(
            maxsize=worker_count
        )
        completed: dict[int, tuple[PreparedAudioChunk | None, BaseException | None]] = {}
        next_spawn = 0
        next_publish = 0
        active = 0
        child_handles: list[WorkerHandle] = []

        def spawn(ordinal: int) -> None:
            chunk = chunks[ordinal]

            def generate(worker_token: CancellationToken) -> None:
                prepared = None
                error = None
                try:
                    if callable(before_chunk):
                        before_chunk(chunk, worker_token)
                    prepared = self._generate_chunk(
                        stream,
                        plan,
                        chunk,
                        adapter,
                        sample_rate,
                        output_directory,
                        worker_token,
                        coordinator_token=coordinator_token,
                    )
                except BaseException as exc:
                    error = exc
                while not self._stopping(stream, worker_token, coordinator_token):
                    try:
                        completions.put((ordinal, prepared, error), timeout=0.05)
                        return
                    except queue.Full:
                        continue
                if prepared is not None:
                    stream.discard_ready(prepared)

            if route_effect_owner is None:
                handle = self._workers.spawn(
                    name="nc-tts-generate",
                    lease=stream.lease,
                    target=generate,
                    identity=("speech_output", stream.speech_id),
                )
            else:
                spawned = route_effect_owner.run_step(
                    "nc-tts-generate_spawn",
                    lambda: self._workers.spawn(
                        name="nc-tts-generate",
                        lease=stream.lease,
                        target=generate,
                        identity=("speech_output", stream.speech_id),
                    ),
                )
                if not spawned.accepted or spawned.value is None:
                    raise RuntimeError(
                        spawned.failure.message
                        if spawned.failure is not None
                        else "Parallel generation lost route authority."
                    )
                handle = spawned.value
            stream._add_handle(handle)
            child_handles.append(handle)

        try:
            while next_spawn < len(chunks) and active < worker_count:
                spawn(next_spawn)
                next_spawn += 1
                active += 1

            while active and not self._stopping(stream, coordinator_token):
                try:
                    ordinal, prepared, error = completions.get(timeout=0.05)
                except queue.Empty:
                    continue
                completed[ordinal] = (prepared, error)
                active -= 1
                while next_publish in completed:
                    prepared, error = completed.pop(next_publish)
                    if error is not None:
                        raise error
                    if prepared is None:
                        return
                    self._notify_prepared_observer(prepared)
                    if not stream._publish(prepared):
                        stream.discard_ready(prepared)
                        return
                    next_publish += 1
                while (
                    next_spawn < len(chunks)
                    and active + len(completed) < worker_count
                ):
                    spawn(next_spawn)
                    next_spawn += 1
                    active += 1
        finally:
            if child_handles:
                self._workers.cancel_handles(
                    child_handles,
                    "speech_prepare_window_closed",
                )
                self._workers.join_handles(child_handles)
            for prepared, _error in completed.values():
                if prepared is not None:
                    stream.discard_ready(prepared)
            try:
                while True:
                    _ordinal, prepared, _error = completions.get_nowait()
                    if prepared is not None:
                        stream.discard_ready(prepared)
            except queue.Empty:
                pass

    def _generate_chunk(
        self,
        stream: SpeechOutputStream,
        plan: SpeechPlan,
        chunk: SpeechChunkPlan,
        adapter,
        sample_rate: int,
        output_directory: Path,
        worker_token: CancellationToken,
        *,
        coordinator_token: CancellationToken | None = None,
    ) -> PreparedAudioChunk | None:
        if self._stopping(stream, worker_token, coordinator_token):
            return None
        policy = self._capabilities.incremental_pcm_allowed
        supports = getattr(adapter, 'supports_incremental_audio', None)
        if (callable(policy) and policy(chunk, plan.config) and callable(supports)
                and supports(plan.config.values) and callable(getattr(adapter, 'generate_stream', None))):
            return self._generate_incremental_chunk(stream, plan, chunk, adapter, sample_rate,
                output_directory, worker_token, coordinator_token)
        gate_wait_started_at = self._capabilities.clock()
        trace_fields = self._trace_fields(stream, plan, chunk, gate_wait_started_at)
        self._trace_safely("tts_generation_start", trace_fields)
        if self._stopping(stream, worker_token, coordinator_token):
            self._trace_safely("tts_generation_cancelled", {
                **trace_fields, "outcome": "cancelled", "stage": "generation_gate",
            })
            return None
        gate_acquired = False
        gate_wait_ms = 0.0
        cache_hit = False
        progressive_source = None
        started_at = gate_wait_started_at
        generation_error = ""
        reservation = getattr(stream, '_generation_reservations', {}).get(getattr(chunk, 'index', None))
        try:
            # Pronunciation-only cleanup for phone replies. Keep chunk.text
            # unchanged for chat history, playback receipts and read-along.
            spoken_text = self._spoken_text(chunk)
            # Private audio is already synthesized and guarded by its own lock.
            # Do not hold a ready playback chunk behind unrelated inference.
            wav = self._private_audio_for(plan, chunk, sample_rate, spoken_text)
            if wav is None:
                gate_wait_started_at = self._capabilities.clock()
                if reservation is not None and not reservation.acquire(
                        cancel_tokens=(stream.token, worker_token, coordinator_token)):
                    return None
                while not self._stopping(stream, worker_token, coordinator_token):
                    gate_acquired = self._generation_gate.acquire(timeout=0.05)
                    if gate_acquired:
                        break
                started_at = self._capabilities.clock()
                gate_wait_ms = max(0.0, (started_at - gate_wait_started_at) * 1000.0)
                if not gate_acquired or self._stopping(stream, worker_token, coordinator_token):
                    self._trace_safely("tts_generation_cancelled", {
                        **trace_fields, "outcome": "cancelled", "stage": "generation_gate",
                    })
                    return None
                # Lookahead may have finished while this worker waited.
                wav = self._private_audio_for(plan, chunk, sample_rate, spoken_text)
            cache_hit = wav is not None
            if wav is None:
                kwargs = self._generation_kwargs(plan, chunk)
                from core.runtime.progressive_phone_audio import (
                    generate_progressive_phone_audio, progressive_phone_audio_allowed,
                )
                if progressive_phone_audio_allowed(chunk.source_metadata, plan.config.values,
                                                   adapter, sample_rate):
                    prefix_path = tts_runtime.new_tts_audio_path(
                        output_directory, chunk.index, speech_id=stream.speech_id + '_prefix')
                    def publish_prefix(source, path):
                        result = self._effect_with_admission(stream.lease,
                            self._capabilities.audio_chunk_ready, {
                                'audio_path': str(path), 'text': chunk.text,
                                'emotion': chunk.expression, 'sequence_index': int(chunk.index),
                                'duration_seconds': 0.0, 'sample_rate': int(sample_rate),
                                'source_meta': dict(chunk.source_metadata),
                                'tts_backend': 'liquidai', 'created_at': time.time(),
                                'progressive_audio_source': source,
                            })
                        return (isinstance(result, Mapping)
                                and result.get('progressive_audio_admitted') is True)
                    wav, progressive_source = generate_progressive_phone_audio(
                        adapter, spoken_text, config=plan.config.values, kwargs=kwargs,
                        prefix_path=prefix_path, publish_prefix=publish_prefix,
                        cancel_tokens=(stream.token, worker_token, coordinator_token),
                        delete_audio=stream._delete_safely)
                else:
                    wav = adapter.generate(spoken_text, **kwargs)
        except BaseException as exc:
            generation_error = type(exc).__name__
            raise
        finally:
            generation_duration_ms = max(
                0.0,
                (self._capabilities.clock() - started_at) * 1000.0,
            )
            if gate_acquired:
                self._generation_gate.release()
            if reservation is not None:
                reservation.release()
            self._trace_safely(
                "tts_generation",
                {
                    **trace_fields,
                    "duration_ms": round(generation_duration_ms, 3),
                    "gate_wait_ms": round(gate_wait_ms, 3),
                    "cache_hit": cache_hit,
                    "outcome": ("error" if generation_error else "cancelled"
                                if self._stopping(stream, worker_token, coordinator_token) else "ok"),
                    "error_class": generation_error,
                },
            )
        if self._stopping(stream, worker_token, coordinator_token):
            if progressive_source is not None:
                progressive_source.cancel('phone_speech_preparation_cancelled')
            return None
        audio_path = tts_runtime.new_tts_audio_path(
            output_directory,
            chunk.index,
            speech_id=stream.speech_id,
        )
        save_started_at = self._capabilities.clock()
        try:
            self._capabilities.save_audio(audio_path, wav, sample_rate)
        except BaseException as exc:
            if progressive_source is not None:
                progressive_source.fail(exc)
            stream._delete_safely(str(audio_path))
            raise
        audio_save_duration_ms = max(
            0.0,
            (self._capabilities.clock() - save_started_at) * 1000.0,
        )
        self._trace_safely(
            "tts_audio_file_saved",
            {
                **trace_fields,
                "duration_ms": round(audio_save_duration_ms, 3),
            },
        )
        if self._stopping(stream, worker_token, coordinator_token):
            if progressive_source is not None:
                progressive_source.cancel('phone_speech_preparation_cancelled')
            stream._delete_safely(str(audio_path))
            return None
        try:
            effect_admission = self._admit_prepared_effect(stream.lease)
        except BaseException:
            effect_admission = None
        if effect_admission is None:
            if progressive_source is not None:
                progressive_source.cancel('phone_speech_preparation_retired')
            stream._delete_safely(str(audio_path))
            return None
        try:
            source_metadata = dict(chunk.source_metadata)
            if progressive_source is not None:
                source_metadata['skip_local_playback'] = True
            if bool(source_metadata.get("publish_tts_addon_events", False)):
                addon_notify_started_at = self._capabilities.clock()
                notifications = self._effect_safely(
                    self._capabilities.audio_chunk_ready,
                    {
                        "audio_path": str(audio_path),
                        "text": chunk.text,
                        "emotion": chunk.expression,
                        "sequence_index": int(chunk.index),
                        "duration_seconds": 0.0,
                        "sample_rate": int(sample_rate),
                        "preparation_timing": {
                            "speech_id": stream.speech_id,
                            "gate_wait_ms": round(gate_wait_ms, 3),
                            "generation_ms": round(generation_duration_ms, 3),
                            "cache_hit": cache_hit,
                        },
                        "source_meta": dict(source_metadata),
                        "tts_backend": str(
                            plan.config.values.get("tts_backend", "") or ""
                        ),
                        "created_at": time.time(),
                        **({'progressive_finalize_source': progressive_source}
                           if progressive_source is not None else {}),
                    },
                )
                if progressive_source is not None and not (
                        isinstance(notifications, Mapping)
                        and notifications.get('progressive_audio_admitted') is True):
                    error = RuntimeError('Phone progressive audio finalization was retired')
                    progressive_source.fail(error)
                    stream._delete_safely(str(audio_path))
                    raise error
                if isinstance(notifications, Mapping) and bool(
                    notifications.get("skip_local_playback", False)
                ):
                    source_metadata["skip_local_playback"] = True
                self._trace_safely(
                    "tts_addon_chunk_notify",
                    {
                        **trace_fields,
                        "duration_ms": round(
                            max(
                                0.0,
                                (
                                    self._capabilities.clock()
                                    - addon_notify_started_at
                                )
                                * 1000.0,
                            ),
                            3,
                        ),
                    },
                )
            prepared = PreparedAudioChunk(
                speech_id=stream.speech_id,
                index=chunk.index,
                text=chunk.text,
                expression=chunk.expression,
                voice_action=chunk.voice_action,
                audio_path=str(audio_path),
                sample_rate=sample_rate,
                lease=stream.lease,
                source_metadata=_frozen_metadata(source_metadata),
                generation_started_at=started_at,
                generation_duration_ms=generation_duration_ms,
                audio_save_duration_ms=audio_save_duration_ms,
            )
            prepare_audio = self._capabilities.prepare_playback_audio
            if prepare_audio is not None:
                try:
                    playback_audio = prepare_audio(prepared, plan.config)
                    prepared = replace(prepared, playback_audio=playback_audio)
                except Exception as exc:
                    # Optional eager preparation must not make usable WAVs unplayable.
                    self._capabilities.logger(f"Audio preparation fallback: {exc}")
            if self._stopping(stream, worker_token, coordinator_token):
                if progressive_source is not None:
                    progressive_source.cancel('phone_speech_preparation_cancelled')
                stream._delete_safely(str(audio_path))
                return None
            return prepared
        finally:
            try:
                self._release_prepared_effect(effect_admission)
            except BaseException:
                pass

    def _register_incremental_source(self, source, stream):
        with self._lock:
            if not self._accepting or stream.closed or stream.cancelled:
                return False
            self._incremental_sources[source] = stream.speech_id
        subscription = [None]
        def changed():
            if source.closed:
                with self._lock:self._incremental_sources.pop(source, None)
                if subscription[0] is not None:subscription[0]()
        subscription[0] = source.subscribe(changed)
        if source.closed:subscription[0]()
        return True

    def _generate_incremental_chunk(self, stream, plan, chunk, adapter, sample_rate,
                                    output_directory, worker_token, coordinator_token):
        from core.incremental_audio import IncrementalAudioSource
        options_callback = getattr(adapter, 'incremental_audio_options', None)
        options = dict(options_callback(plan.config.values) or {}) if callable(options_callback) else {}
        spoken_text = self._spoken_text(chunk)
        source = IncrementalAudioSource(sample_rate=sample_rate, channels=1,
            startup_seconds=options.get('startup_buffer_seconds', 1.),
            estimated_duration_seconds=max(.1, len(spoken_text)/14.),
            output_directory=output_directory)
        source.speech_id = stream.speech_id
        source.chunk_index = chunk.index
        if not self._register_incremental_source(source, stream):
            source.close()
            return None
        started = [self._capabilities.clock()]
        queued_fields = self._trace_fields(stream, plan, chunk, started[0])
        performance_fields = {key: queued_fields[key] for key in
            ('speech_id', 'sequence', 'engine_mode', 'trace_id', 'elapsed_ms')}
        performance_fields['tts_backend'] = str(plan.config.values.get('tts_backend', '') or '')
        performance_fields['startup_buffer_seconds'] = source.startup_seconds
        # These preparation-only tokens lose ownership when the ready header returns.
        preparation_subscriptions = [token.subscribe(lambda token=token: source.cancel(token.reason))
            for token in (worker_token, coordinator_token) if token is not None]
        def produce(producer_token):
            subscriptions = [token.subscribe(lambda token=token: source.cancel(token.reason))
                for token in (stream.token, producer_token)]
            acquired = False
            iterator = None
            fields = self._trace_fields(stream, plan, chunk, started[0])
            gate_started = self._capabilities.clock()
            order_finished = gate_started
            generation_started = None
            first_pcm_recorded = False
            error = None
            reservation = stream._generation_reservations.get(chunk.index)
            try:
                if reservation is not None:
                    ordered = reservation.acquire(cancel_tokens=(source.token,))
                    order_finished = self._capabilities.clock()
                    if not ordered:
                        raise InterruptedError(source.token.reason or 'Ordered synthesis cancelled')
                acquired = self._generation_gate.acquire(cancel_tokens=(source.token,))
                if not acquired or source.cancelled:
                    raise InterruptedError(source.token.reason or 'Incremental synthesis cancelled')
                started[0] = self._capabilities.clock()
                generation_started = started[0]
                _record_performance('tts_generation_start', **performance_fields,
                    gate_wait_ms=max(0., (generation_started-gate_started)*1000),
                    order_wait_ms=max(0., (order_finished-gate_started)*1000),
                    generation_gate_wait_ms=max(0., (generation_started-order_finished)*1000))
                self._trace_safely('tts_generation_start', {**fields, 'incremental_pcm': True})
                kwargs = self._generation_kwargs(plan, chunk)
                iterator = adapter.generate_stream(spoken_text, stop_event=source.token, **kwargs)
                for block in iterator:
                    if source.cancelled:raise InterruptedError(source.token.reason)
                    source.append(block)
                    if not first_pcm_recorded and source.frame_count:
                        first_pcm_recorded = True
                        _record_performance('tts_first_pcm', **performance_fields,
                            duration_ms=max(0., (self._capabilities.clock()-generation_started)*1000),
                            frame_count=source.frame_count, sample_rate=source.sample_rate)
                source.finish()
            except BaseException as exc:
                error = exc
                source.fail(exc)
                if not source.cancelled:
                    stream._mark_failure(RuntimeFailure('tts_incremental_generation_failed',
                        f'Incremental speech generation failed: {exc}', exc))
            finally:
                if iterator is not None:
                    close = getattr(iterator, 'close', None)
                    if callable(close):
                        try:close()
                        except BaseException as exc:
                            source.fail(exc)
                if acquired:self._generation_gate.release()
                if reservation is not None:reservation.release()
                for unsubscribe in subscriptions:unsubscribe()
                generation_ended = self._capabilities.clock()
                admission_ended = generation_started if generation_started is not None else generation_ended
                _record_performance('tts_generation_end', **performance_fields,
                    duration_ms=max(0., (generation_ended-generation_started)*1000)
                        if generation_started is not None else 0.,
                    gate_wait_ms=max(0., (admission_ended-gate_started)*1000),
                    order_wait_ms=max(0., (order_finished-gate_started)*1000),
                    generation_gate_wait_ms=max(0., (admission_ended-order_finished)*1000),
                    frame_count=source.frame_count, sample_rate=source.sample_rate,
                    audio_duration_seconds=source.duration_seconds,
                    outcome='cancelled' if source.cancelled else 'error' if source.error else 'ok')
                self._trace_safely('tts_generation', {**fields,
                    'duration_ms':round(max(0., (self._capabilities.clock()-started[0])*1000),3),
                    'gate_wait_ms':round(max(0., (started[0]-gate_started)*1000),3),
                    'cache_hit':False, 'incremental_pcm':True,
                    'outcome':'cancelled' if source.cancelled else 'error' if error else 'ok',
                    'error_class':type(error).__name__ if error else ''})
        try:
            self._trace_safely('tts_incremental_queued', queued_fields)
            _record_performance('tts_incremental_queued', **performance_fields)
            handle = self._workers.spawn(name='nc-tts-pcm-produce', lease=stream.lease,
                target=produce, on_cancel=source.cancel,
                identity=('speech_output', stream.speech_id, 'pcm', chunk.index), owner_token=source)
            stream._add_handle(handle)
            source.wait_ready()
            if self._stopping(stream, worker_token, coordinator_token):
                source.close()
                return None
            admission = self._admit_prepared_effect(stream.lease)
            if admission is None:
                source.close()
                return None
            try:
                _record_performance('tts_incremental_ready', **performance_fields,
                    frame_count=source.frame_count, sample_rate=source.sample_rate,
                    audio_duration_seconds=source.duration_seconds)
                return PreparedAudioChunk(speech_id=stream.speech_id, index=chunk.index,
                    text=chunk.text, expression=chunk.expression, voice_action=chunk.voice_action,
                    audio_path='', sample_rate=sample_rate, lease=stream.lease,
                    source_metadata=_frozen_metadata(chunk.source_metadata),
                    generation_started_at=started[0],
                    generation_duration_ms=max(0., (self._capabilities.clock()-started[0])*1000),
                    audio_save_duration_ms=0., audio_source=source)
            finally:self._release_prepared_effect(admission)
        except BaseException:
            source.close()
            raise
        finally:
            for unsubscribe in preparation_subscriptions:unsubscribe()

    def _notify_prepared_observer(self, prepared: PreparedAudioChunk) -> None:
        """Notify visual preparation only after generation is logically ordered."""

        observer = self._prepared_observer
        if observer is None:
            return
        try:
            admission = self._admit_prepared_effect(prepared.lease)
        except BaseException:
            return
        if admission is None:
            return
        try:
            observer(prepared)
        except BaseException:
            pass
        finally:
            try:
                self._release_prepared_effect(admission)
            except BaseException:
                pass

    @staticmethod
    def _trace_fields(
        stream: SpeechOutputStream,
        plan: SpeechPlan,
        chunk: SpeechChunkPlan,
        started_at: float,
    ) -> dict[str, object]:
        metadata = chunk.source_metadata
        pipeline_started_at = float(metadata.get("tts_pipeline_started_at", started_at) or started_at)
        return {
            "trace_id": str(metadata.get("tts_trace_id", "") or ""),
            "elapsed_ms": round(max(0.0, (started_at - pipeline_started_at) * 1000.0), 3),
            "chunk_chars": len(chunk.text),
            "text": chunk.text,
            "sequence": int(chunk.index),
            "engine_mode": str(
                plan.config.values.get("avatar_mode", "vseeface") or "vseeface"
            ).strip().lower(),
            "streaming": bool(metadata.get("speech_route_streaming", False)),
            "replay": bool(metadata.get("tts_replay", False)),
            "replay_index": int(metadata.get("replay_index", 0) or 0),
            "source_offset": int(metadata.get("tts_source_offset", 0) or 0),
            "voice_override": bool(chunk.voice_path),
            "speech_id": stream.speech_id,
            "speech_session_generation": (
                stream.lease.session_generation.value if stream.lease.session_generation is not None else None
            ),
            "speech_transaction_id": str(metadata.get("normal_chat_transaction_id") or ""),
            "speech_message_id": str(metadata.get("replay_message_id") or ""),
            "speech_hidden": bool(metadata.get("companion_orb_response") or metadata.get("hidden_proactive")),
            "config_revision": int(plan.config.revision),
        }

    def _trace_safely(self, event: str, fields: Mapping[str, object]) -> None:
        try:
            self._capabilities.trace(str(event), dict(fields))
        except BaseException:
            pass

    @staticmethod
    def _effect_safely(
        callback: SpeechEffect,
        payload: Mapping[str, object],
    ) -> object:
        try:
            return callback(dict(payload))
        except BaseException:
            return None

    def _effect_with_admission(
        self,
        lease: WorkLease,
        callback: SpeechEffect,
        payload: Mapping[str, object],
    ) -> object:
        try:
            admission = self._admit_prepared_effect(lease)
        except BaseException:
            return None
        if admission is None:
            return None
        try:
            return self._effect_safely(callback, payload)
        finally:
            try:
                self._release_prepared_effect(admission)
            except BaseException:
                pass

    @staticmethod
    def _stopping(
        stream: SpeechOutputStream,
        *tokens: CancellationToken | None,
    ) -> bool:
        if stream.cancelled or stream.closed:
            return True
        return any(token is not None and token.cancelled for token in tokens)

    def _cancel_stream(self, stream: SpeechOutputStream, reason: str) -> None:
        from core.incremental_audio import IncrementalAudioSource
        soft_close = reason == 'speech_stream_closed'
        buffered = () if soft_close else stream._cancel_from_service(str(reason or "speech_cancelled"))
        with self._lock:
            sources = tuple(source for source, speech_id in self._incremental_sources.items()
                            if speech_id == stream.speech_id)
        for source in sources:
            if not soft_close:source.cancel(str(reason or "speech_cancelled"))
            if not soft_close or not source.playback_owned:source.close()
        handles = tuple(handle for handle in stream._handles_snapshot()
                        if not (soft_close and isinstance(handle.owner_token, IncrementalAudioSource)
                                and handle.owner_token.playback_owned))
        if handles:
            self._workers.cancel_handles(handles, str(reason or "speech_cancelled"))
        for prepared in buffered:
            stream.discard_ready(prepared)

    def _close_stream(self, stream: SpeechOutputStream) -> None:
        with self._lock:
            if self._streams.get(stream.speech_id) is stream:
                self._streams.pop(stream.speech_id, None)
            unowned = tuple(source for source, speech_id in self._incremental_sources.items()
                            if speech_id == stream.speech_id and not source.playback_owned)
        for source in unowned:source.close()


__all__ = [
    "PreparedAudioChunk",
    "PreparedAudioHandoff",
    "SpeechChunkPlan",
    "SpeechOutputCapabilities",
    "SpeechOutputService",
    "SpeechOutputStream",
    "SpeechPlan",
]
